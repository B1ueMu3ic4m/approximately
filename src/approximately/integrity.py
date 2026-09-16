"""Tamper-evident evidence chains for recorded traces.

A postmortem is only as good as the trustworthiness of its evidence. When
an agent run matters — incidents, compliance, "why did it charge the
customer twice" — the recorded trajectory must be able to prove it has not
been altered after the fact.

Mistral-style hash chain (same construction as certificate transparency):

    seed  = sha256(task | model | created_at)
    h[i]  = sha256(h[i-1] || canonical_json(step[i]))
    final = h[last]

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
from typing import List, Optional

from .trace import Trace

ALGORITHM = "sha256-chain-v1"
ALGORITHM_KEYED = "hmac-sha256-chain-v1"


def _canonical(step_dict: dict) -> bytes:
    return json.dumps(step_dict, sort_keys=True, default=str).encode("utf-8")


def _sha(data: bytes) -> str:
    # integrity fingerprinting only, never security-secret material
    return hashlib.sha256(data, usedforsecurity=False).hexdigest()


def _mac(key: bytes, data: bytes) -> str:
    return hmac.new(key, data, hashlib.sha256).hexdigest()


def load_key(key_file: Optional[str] = None) -> Optional[bytes]:
    """Signing key: explicit file, else APPROXIMATELY_SIGNING_KEY (hex or text)."""
    if key_file:
        path = Path(key_file)
        if not path.is_file():
            return None
        return path.read_bytes().strip()
    env = os.environ.get("APPROXIMATELY_SIGNING_KEY")
    if not env:
        return None
    try:
        return bytes.fromhex(env)
    except ValueError:
        return env.encode("utf-8")


def _seed(trace: Trace) -> str:
    seed_input = f"{trace.task}|{trace.model}|{trace.created_at}"
    return _sha(seed_input.encode("utf-8"))


def compute_chain(trace: Trace, key: Optional[bytes] = None) -> List[str]:
    """Walk the chain over the trace's steps as they are right now.

    Without a key this is a plain sha256 chain (detects accidental or lazy
    tampering). With a key it is an HMAC-SHA256 chain: an attacker with
    write access to the file can no longer recompute the chain, so forgery
    is detectable by anyone holding the key.
    """
    if key is not None:
        def digest(msg: bytes) -> str:
            return _mac(key, msg)
    else:
        def digest(msg: bytes) -> str:
            return _sha(msg)
    hashes = []
    previous = _seed(trace)
    for step in trace.steps:
        previous = digest(previous.encode("utf-8") + _canonical(step.to_dict()))
        hashes.append(previous)
    return hashes


def key_id(key: bytes) -> str:
    """Short identifier of a signing key, stamped into keyed blocks.

    Lets `verify` distinguish *evidence broken* (TAMPERED) from *evidence
    signed with a different key* (wrong-key), and lets `rotate` keep a
    per-trace rotation counter.
    """
    return _sha(b"key-id:" + key)[:8]


def sign(trace: Trace, key: Optional[bytes] = None) -> dict:
    """Stamp an integrity block into ``trace.meta`` (recorder calls this)."""
    chain = compute_chain(trace, key=key)
    block = {
        "algorithm": ALGORITHM_KEYED if key else ALGORITHM,
        "keyed": key is not None,
        "seed": _seed(trace),
        "step_hashes": chain,
        "final": chain[-1] if chain else _seed(trace),
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


def _effective_key(block: dict, key: Optional[bytes]):
    """Resolve the verification key for a stamped trace.

    Returns ``None`` for unkeyed traces, the key for keyed traces, and the
    ``_LOCKED`` sentinel when a keyed trace cannot be verified for lack of
    the key.
    """
    keyed = bool(block.get("keyed")) and block.get("algorithm") == ALGORITHM_KEYED
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
    block = trace.meta.get("integrity")
    if not block or block.get("algorithm") not in (ALGORITHM, ALGORITHM_KEYED):
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

    actual = compute_chain(trace, key=key)
    expected_hashes: List[str] = block.get("step_hashes", [])
    if actual == expected_hashes:
        return _intact_result(block, actual)
    return _tamper_result(block, actual, expected_hashes)


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
        (i for i, (a, e) in enumerate(zip(actual, expected)) if a != e),
        min(len(actual), len(expected)),
    )
    return VerificationResult(
        signed=True, intact=False, first_bad_step=first_bad,
        expected_final=block.get("final"),
        actual_final=actual[-1] if actual else None,
        detail=(f"step #{first_bad} no longer matches its recorded hash; "
                "everything after it is also untrusted"),
    )
