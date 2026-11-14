"""Tamper-evident evidence chains for recorded traces.

A postmortem is only as good as the trustworthiness of its evidence. When
an agent run matters — incidents, compliance, "why did it charge the
customer twice" — the recorded trajectory must be able to prove it has not
been altered after the fact.

Mistral-style hash chain (same construction as certificate transparency).
v2 (the 5.0.0 contract change — the audit showed v1 left the postmortem
consumers' fields outside the fence):

    header = canonical_json({id, task, model, created_at, success,
                             final_output, meta (minus integrity)})
    seed   = H(header)
    h[i]   = H(h[i-1] || canonical_json(step_view[i]))
    final  = h[last]

v2 hashes the COERCED view of every step (``Trace.from_dict`` is the
v4.2.1 boundary: counters clamp, epochs refuse non-finite) — sign and
verify hash the same truth, so a clamp-eligible value stamped by the
recorder never false-fails its own verdict. v1 covered the steps and
three header fields only: success/final_output/meta/id edits verified
intact, and a text editor could forge or erase the budget-breach stamp.
v1 records still verify under v1 rules and are named as such
(``intact-legacy``) — history is never rewritten.

The recorder stamps ``trace.meta["integrity"]`` on save. ``verify`` then
recomputes the chain over the stored steps and localizes the first step
that no longer matches — tampering cannot pass undetected without
recomputing the entire chain, and any edit is visible as a broken link.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

from .trace import Trace

ALGORITHM = "sha256-chain-v2"
ALGORITHM_KEYED = "hmac-sha256-chain-v2"
ALGORITHM_V1 = "sha256-chain-v1"
ALGORITHM_KEYED_V1 = "hmac-sha256-chain-v1"


def _canonical(step_dict: dict) -> bytes:
    return json.dumps(step_dict, sort_keys=True, default=str).encode("utf-8")


def _sha(data: bytes) -> str:
    # integrity fingerprinting only, never security-secret material
    return hashlib.sha256(data, usedforsecurity=False).hexdigest()


def _mac(key: bytes, data: bytes) -> str:
    return hmac.new(key, data, hashlib.sha256).hexdigest()


MAX_KEY_FILE_BYTES = 4096


def load_key(key_file: Optional[str] = None) -> Optional[bytes]:
    """Signing key: explicit file, else APPROXIMATELY_SIGNING_KEY (hex or text).

    The file read is capped at ``MAX_KEY_FILE_BYTES``: a key is tiny,
    so a bigger file is a mistake or a resource-exhaustion attempt
    (point the flag at a multi-gigabyte file and an unbounded read
    would balloon memory) — refuse it instead.
    """
    if key_file:
        path = Path(key_file)
        if not path.is_file():
            # an explicitly named key that does not exist is a
            # named refusal, not a silent downgrade to an
            # unkeyed (forgeable) chain
            raise ValueError(f"key file {key_file!r} not found")
        with path.open("rb") as fh:
            data = fh.read(MAX_KEY_FILE_BYTES + 1)
        if len(data) > MAX_KEY_FILE_BYTES:
            raise ValueError(
                f"key file {key_file!r} is larger than "
                f"{MAX_KEY_FILE_BYTES} bytes — that is not a key; "
                "refusing to read it")
        return data.strip()
    env = os.environ.get("APPROXIMATELY_SIGNING_KEY")
    if not env:
        return None
    try:
        return bytes.fromhex(env)
    except ValueError:
        return env.encode("utf-8")


def _hash_view(trace: Trace) -> Trace:
    """The trace as the chain sees it: the coerced round-trip.
    v4.2.1 made ``from_dict`` the data boundary (counters clamp,
    epochs refuse non-finite, names stay names) — sign and verify
    hash that same view, so the recorder's own out-of-band values
    never false-fail their own verdict, and a hostile import
    arrives as exactly what the verifier will recompute."""
    return Trace.from_dict(trace.to_dict())


def _header(trace: Trace) -> dict:
    """The postmortem consumers' fields, inside the fence: id,
    verdict, output, and every meta key — including the budget
    breach stamp, which a text editor could previously forge or
    erase. The integrity block itself is excluded (it carries the
    hash that covers it)."""
    meta = trace.meta if isinstance(trace.meta, dict) else {}
    return {
        "id": trace.id,
        "task": trace.task,
        "model": trace.model,
        "created_at": trace.created_at,
        "success": trace.success,
        "final_output": trace.final_output,
        "meta": {k: v for k, v in meta.items()
                 if k != "integrity"},
    }


def _seed_v2(trace: Trace) -> str:
    return _sha(_canonical(_header(_hash_view(trace))))


def _seed_v1(trace: Trace) -> str:
    """The v1 seed: three header fields, f-string joined. Kept
    for legacy verdicts — history is never rewritten."""
    seed_input = f"{trace.task}|{trace.model}|{trace.created_at}"
    return _sha(seed_input.encode("utf-8"))


def _chain(trace: Trace, key: Optional[bytes], seed: str,
           steps: list) -> List[str]:
    def digest(msg: bytes) -> str:
        return _mac(key, msg) if key is not None else _sha(msg)
    hashes = []
    previous = seed
    for step in steps:
        previous = digest(previous.encode("utf-8")
                          + _canonical(step.to_dict()))
        hashes.append(previous)
    return hashes


def compute_chain(trace: Trace, key: Optional[bytes] = None) -> List[str]:
    """Walk the v2 chain over the coerced view of the trace.

    Without a key this is a plain sha256 chain (detects accidental or lazy
    tampering). With a key it is an HMAC-SHA256 chain: an attacker with
    write access to the file can no longer recompute the chain, so forgery
    is detectable by anyone holding the key.
    """
    view = _hash_view(trace)
    return _chain(view, key, _seed_v2(view), view.steps)


def _chain_v1(trace: Trace, key: Optional[bytes] = None) -> List[str]:
    """The v1 walker, unchanged, for legacy verdicts."""
    return _chain(trace, key, _seed_v1(trace), trace.steps)


def key_id(key: bytes) -> str:
    """Short identifier of a signing key, stamped into keyed blocks.

    Lets `verify` distinguish *evidence broken* (TAMPERED) from *evidence
    signed with a different key* (wrong-key), and lets `rotate` keep a
    per-trace rotation counter.
    """
    return _sha(b"key-id:" + key)[:8]


def sign(trace: Trace, key: Optional[bytes] = None) -> dict:
    """Stamp a v2 integrity block into ``trace.meta`` (the recorder
    calls this). The block covers the coerced view of every step
    and every postmortem field — id, verdict, output, meta (the
    breach stamp included)."""
    view = _hash_view(trace)
    chain = compute_chain(view, key=key)
    block = {
        "algorithm": ALGORITHM_KEYED if key else ALGORITHM,
        "keyed": key is not None,
        "seed": _seed_v2(view),
        "step_hashes": chain,
        "final": chain[-1] if chain else _seed_v2(view),
    }
    if key is not None:
        block["key_id"] = key_id(key)
        # preserve the rotation counter across re-signing (rotate uses it)
        previous = trace.meta.get("integrity") or {}
        block["rotations"] = int(previous.get("rotations", 0))
    previous = trace.meta.get("integrity") or {}
    block["resign_count"] = int(previous.get("resign_count", 0)) + 1
    trace.meta["integrity"] = block
    return block


@dataclass
class VerificationResult:
    signed: bool
    intact: bool = False
    first_bad_step: Optional[int] = None  # None when intact (or unsigned)
    expected_final: Optional[str] = None
    actual_final: Optional[str] = None
    detail: str = ""
    verdict_override: Optional[str] = None  # e.g. "keyed": locked, not broken

    @property
    def verdict(self) -> str:
        if self.verdict_override:
            return self.verdict_override
        if not self.signed:
            return "unsigned"
        return "intact" if self.intact else "TAMPERED"


def rotate(trace: Trace, old_key: Optional[bytes],
           new_key: bytes) -> VerificationResult:
    """Re-key a signed trace: verify with the old key, re-sign with the new.

    Raises ValueError when the old key does not verify (refusing to rotate
    a trace whose evidence is already broken). Each successful rotation
    bumps the block's ``rotations`` counter, so the audit trail shows how
    often the evidence has been re-keyed.
    """
    result = verify(trace, key=old_key)
    if result.verdict not in ("intact", "unsigned"):
        raise ValueError(f"cannot rotate a {result.verdict} trace: "
                         f"{result.detail}")
    sign(trace, key=new_key)
    trace.meta["integrity"]["rotations"] = \
        int((trace.meta.get("integrity") or {}).get("rotations", 0)) + 1
    return result


_LOCKED = object()  # sentinel: keyed trace, but no key available


def _effective_key(block: dict, key: Optional[bytes]) -> Any:
    """Resolve the verification key for a stamped trace.

    Returns ``None`` for unkeyed traces, the key for keyed traces, and the
    ``_LOCKED`` sentinel when a keyed trace cannot be verified for lack of
    the key.
    """
    keyed = bool(block.get("keyed")) and block.get("algorithm") in (
        ALGORITHM_KEYED, ALGORITHM_KEYED_V1)
    if not keyed:
        return None
    if not key:
        key = load_key()
    return key if key else _LOCKED


def verify(trace: Trace, key: Optional[bytes] = None) -> VerificationResult:
    """Recompute the chain and compare against the stamped integrity block.

    Keyed traces require the same key. Verifying a keyed trace without the
    key returns verdict ``keyed`` — the evidence is locked, not broken.
    """
    meta = trace.meta if isinstance(trace.meta, dict) else {}
    block = meta.get("integrity")
    if not isinstance(block, dict) or block.get("algorithm") not in (
            ALGORITHM, ALGORITHM_KEYED, ALGORITHM_V1,
            ALGORITHM_KEYED_V1):
        return VerificationResult(signed=False,
                                  detail="trace carries no integrity block")

    key = _effective_key(block, key)
    if key is _LOCKED:
        return VerificationResult(
            signed=True, intact=False,
            detail=("trace is HMAC-keyed; pass the signing key "
                    "(--key-file or APPROXIMATELY_SIGNING_KEY) to verify"),
            verdict_override="keyed",
        )
    if key is not None and block.get("key_id") \
            and key_id(key) != block.get("key_id"):
        # a different (older/newer) key signed this evidence: it is
        # locked, not broken — accusing TAMPERED here would be wrong
        return VerificationResult(
            signed=True, intact=False,
            detail=(f"evidence signed with key {block.get('key_id')}; "
                    f"the supplied key has id {key_id(key)} "
                    "(rotate first, then verify)"),
            verdict_override="wrong-key",
        )

    legacy = block.get("algorithm") in (ALGORITHM_V1,
                                        ALGORITHM_KEYED_V1)
    # v1 records verify under v1 rules: history is never rewritten,
    # and the verdict names the format so an auditor knows which
    # fence the evidence stood behind
    actual = (_chain_v1(trace, key=key) if legacy
              else compute_chain(trace, key=key))
    expected_hashes: List[str] = block.get("step_hashes", [])
    if actual == expected_hashes:
        result = _intact_result(block, actual)
        if legacy:
            result.verdict_override = "intact-legacy"
            result.detail += (" · legacy v1 format (steps only; "
                              "re-sign to bring every field "
                              "inside the fence)")
        return result
    result = _tamper_result(block, actual, expected_hashes)
    if legacy:
        result.detail += " (legacy v1 format)"
    return result


def _intact_result(block: dict, actual: List[str]) -> VerificationResult:
    detail = f"{len(actual)} steps verified"
    if block.get("resign_count", 0) > 1:
        detail += f" · re-signed {block['resign_count'] - 1}x"
    if block.get("keyed"):
        detail += (f" with key {block.get('key_id', '?')}"
                   f" · rotations: {block.get('rotations', 0)}")
    return VerificationResult(
        signed=True, intact=True,
        expected_final=block.get("final"),
        actual_final=actual[-1] if actual else block.get("seed"),
        detail=detail,
    )


def _tamper_result(block: dict, actual: List[str],
                   expected: List[str]) -> VerificationResult:
    """Localize the first divergent step of a broken chain."""
    first_bad = next(
        (i for i, (a, e) in enumerate(zip(actual, expected, strict=False)) if a != e),
        min(len(actual), len(expected)),
    )
    return VerificationResult(
        signed=True, intact=False, first_bad_step=first_bad,
        expected_final=block.get("final"),
        actual_final=actual[-1] if actual else None,
        detail=(f"step #{first_bad} no longer matches its recorded hash; "
                "everything after it is also untrusted"),
    )


def verdict_payload(trace: Trace, directory: Any, key: Optional[bytes] = None) -> dict:
    """The verification ladder as one machine-readable object.

    Shared by the CLI (``verify <id> --json``) and the MCP ``verify``
    tool so both surfaces answer with the same data. Rungs:
    ``intact``, ``tampered``, ``unsigned``, ``keyed``, ``wrong-key``,
    ``rolled-back``, ``ledger-broken`` — a wrong-key match lands with
    the locked-not-broken family instead of masquerading as tampered.
    """
    result = verify(trace, key=key)
    if result.verdict == "unsigned":
        return {"verdict": "unsigned", "intact": False,
                "detail": result.detail}
    if result.verdict in ("keyed", "wrong-key"):
        return {"verdict": result.verdict, "intact": False,
                "detail": result.detail}
    if not result.intact:
        return {"verdict": "tampered", "intact": False,
                "detail": result.detail,
                "expected_final": result.expected_final,
                "actual_final": result.actual_final}

    from .ledger import audit_rollback, verify_ledger

    ledger_check = verify_ledger(directory)
    if audit_rollback(trace, directory):
        return {"verdict": "rolled-back", "intact": True,
                "detail": ("an older signed state of this trace is in "
                           "the evidence ledger; newer saves were "
                           "recorded afterwards"),
                "actual_final": result.actual_final}
    if ledger_check.entries and not ledger_check.intact:
        return {"verdict": "ledger-broken", "intact": True,
                "detail": ledger_check.detail,
                "actual_final": result.actual_final}
    return {"verdict": "intact", "intact": True,
            "detail": result.detail,
            "actual_final": result.actual_final,
            "authenticated": bool(key),
            "rollback": False,
            "ledger": {"entries": ledger_check.entries,
                       "intact": ledger_check.intact}}
