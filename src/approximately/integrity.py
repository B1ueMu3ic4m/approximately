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
    a trace whose evidence is already broken).
    """
    result = verify(trace, key=old_key)
    if result.verdict not in ("intact", "unsigned"):
        raise ValueError(f"cannot rotate a {result.verdict} trace: "
                         f"{result.detail}")
    sign(trace, key=new_key)
    return result


def verify(trace: Trace, key: Optional[bytes] = None) -> VerificationResult:
    """Recompute the chain and compare against the stamped integrity block.

    Keyed traces require the same key. Verifying a keyed trace without the
    key returns verdict ``keyed`` — the evidence is locked, not broken.
    """
    block = trace.meta.get("integrity")
    if not block or block.get("algorithm") not in (ALGORITHM, ALGORITHM_KEYED):
        return VerificationResult(signed=False,
                                  detail="trace carries no integrity block")
    if block.get("keyed") and block.get("algorithm") == ALGORITHM_KEYED:
        if not key:
            key = load_key()
        if not key:
            return VerificationResult(
                signed=True, intact=False,
                detail=("trace is HMAC-keyed; pass the signing key "
                        "(--key-file or APPROXIMATELY_SIGNING_KEY) to verify"),
                verdict_override="keyed",
            )
    actual = compute_chain(trace, key=key if block.get("keyed") else None)
    expected_hashes: List[str] = block.get("step_hashes", [])
    if actual == expected_hashes:
        return VerificationResult(
            signed=True, intact=True,
            expected_final=block.get("final"),
            actual_final=actual[-1] if actual else block.get("seed"),
            detail=f"{len(actual)} steps verified",
        )
    first_bad = next(
        (i for i, (a, e) in enumerate(zip(actual, expected_hashes)) if a != e),
        min(len(actual), len(expected_hashes)),
    )
    return VerificationResult(
        signed=True, intact=False, first_bad_step=first_bad,
        expected_final=block.get("final"),
        actual_final=actual[-1] if actual else None,
        detail=(f"step #{first_bad} no longer matches its recorded hash; "
                "everything after it is also untrusted"),
    )
