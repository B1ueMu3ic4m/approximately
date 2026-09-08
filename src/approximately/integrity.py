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
import json
from dataclasses import dataclass
from typing import List, Optional

from .trace import Trace

ALGORITHM = "sha256-chain-v1"


def _canonical(step_dict: dict) -> bytes:
    return json.dumps(step_dict, sort_keys=True, default=str).encode("utf-8")


def _sha(data: bytes) -> str:
    # integrity fingerprinting only, never security-secret material
    return hashlib.sha256(data, usedforsecurity=False).hexdigest()


def _seed(trace: Trace) -> str:
    seed_input = f"{trace.task}|{trace.model}|{trace.created_at}"
    return _sha(seed_input.encode("utf-8"))


def compute_chain(trace: Trace) -> List[str]:
    """Walk the hash chain over the trace's steps as they are right now."""
    hashes = []
    previous = _seed(trace)
    for step in trace.steps:
        previous = _sha(previous.encode("utf-8") + _canonical(step.to_dict()))
        hashes.append(previous)
    return hashes


def sign(trace: Trace) -> dict:
    """Stamp an integrity block into ``trace.meta`` (recorder calls this)."""
    chain = compute_chain(trace)
    block = {
        "algorithm": ALGORITHM,
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

    @property
    def verdict(self) -> str:
        if not self.signed:
            return "unsigned"
        return "intact" if self.intact else "TAMPERED"


def verify(trace: Trace) -> VerificationResult:
    """Recompute the chain and compare against the stamped integrity block."""
    block = trace.meta.get("integrity")
    if not block or block.get("algorithm") != ALGORITHM:
        return VerificationResult(signed=False,
                                  detail="trace carries no integrity block")
    actual = compute_chain(trace)
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
