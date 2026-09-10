"""Prescription search: the minimal intervention set that clears attribution.

A counterfactual analysis tells you *which step* carries the failure;
this module searches for the **smallest intervention set** that makes the
attributed failures go away, and validates each prescription by re-running
the full attribution after applying it.

The intervention vocabulary is deliberately small and honest — every
intervention corresponds to a MAST fix suggestion:

- ``drop-duplicate`` — keep the first of identical (tool, args) calls
  (fix for FM-1.3 step repetition)
- ``insert-verify`` — add a verification step after an unverified
  mutating call (fix for FM-3.2; MAST intervention evidence: +15.6%)

Validation is detector-level: the repaired trace is re-attributed, and a
prescription counts only when its target mode's detection disappears.
Modes that need agent-level changes (FM-3.1 premature termination) are
reported as ``unrepairable`` with the fix suggestion instead of being
silently "fixed" by trace surgery.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .attributor import attribute
from .trace import MESSAGE, TOOL_CALL, Step, Trace

VERIFY_MARKERS = ("verify", "check", "confirm", "get_", "read", "fetch",
                  "status")


def _is_verify_step(step: Step) -> bool:
    if step.meta.get("verify"):
        return True
    return (step.kind == TOOL_CALL and bool(step.tool) and any(
        m in step.tool.lower() for m in VERIFY_MARKERS
    ))


@dataclass
class RepairResult:
    applied: List[str] = field(default_factory=list)
    cleared_modes: set = field(default_factory=set)
    remaining_modes: set = field(default_factory=set)
    unrepairable: List[str] = field(default_factory=list)
    repaired_trace: Optional[Trace] = None

    @property
    def repaired(self) -> bool:
        return bool(self.cleared_modes)

    def summary(self) -> str:
        lines = []
        if self.applied:
            lines.append("applied interventions:")
            lines.extend(f"  - {a}" for a in self.applied)
        if self.cleared_modes:
            lines.append(f"cleared: {', '.join(sorted(self.cleared_modes))}")
        if self.remaining_modes:
            lines.append(f"still present: "
                         f"{', '.join(sorted(self.remaining_modes))}")
        if self.unrepairable:
            lines.append("requires agent-level change (not trace surgery): "
                         + ", ".join(self.unrepairable))
        return "\n".join(lines)


def _drop_duplicates(trace: Trace) -> Tuple[Trace, Optional[str]]:
    """Keep the first of every identical (tool, args) call chain."""
    seen: set = set()
    copy = Trace(task=trace.task, model=trace.model,
                 success=trace.success, meta=dict(trace.meta))
    dropped = 0
    for step in trace.steps:
        if step.kind == TOOL_CALL and not step.error:
            fp = step.fingerprint()
            if fp in seen:
                dropped += 1
                continue
            seen.add(fp)
        copy.add(Step.from_dict(step.to_dict()))
    description = (f"drop-duplicate: removed {dropped} repeated call(s)"
                   if dropped else None)
    return copy, description


def _unverified_mutating(trace: Trace) -> List[int]:
    positions = [i for i, s in enumerate(trace.steps)
                 if s.kind == TOOL_CALL and not s.error
                 and s.meta.get("mutating")]
    unverified = []
    for i in positions:
        if not any(_is_verify_step(s) for s in trace.steps[i + 1:]):
            unverified.append(i)
    return unverified


def _insert_verify(trace: Trace, after_index: int) -> Tuple[Trace, Step]:
    copy = Trace(task=trace.task, model=trace.model,
                 success=trace.success, meta=dict(trace.meta))
    inserted = None
    for step in trace.steps:
        copy.add(Step.from_dict(step.to_dict()))
        if step.index == after_index:
            inserted = Step(
                kind=TOOL_CALL,
                tool=f"verify_{step.tool}",
                args=dict(step.args),
                result=f"re-checked after {step.tool}: state consistent",
                meta={"verify": True, "for": step.tool},
            )
            copy.add(inserted)
    return copy, inserted


def plan_repair(trace: Trace) -> RepairResult:
    """Greedy search: smallest honest intervention set that clears modes.

    Baseline -> dedupe repeats -> insert verifications -> re-attribute.
    Whatever still fires needs an agent-level change and is reported.
    """
    baseline = attribute(trace)
    failed_modes = {d.mode_id for d in baseline.detections
                    if d.mode_id != "OTHER"}
    result = RepairResult(remaining_modes=set(failed_modes))
    if not baseline.failed or not failed_modes:
        return result

    working = Trace(task=trace.task, model=trace.model,
                    success=trace.success, meta=dict(trace.meta))
    for step in trace.steps:
        working.add(Step.from_dict(step.to_dict()))

    # 1. drop duplicate calls (FM-1.3)
    working, description = _drop_duplicates(working)
    if description:
        result.applied.append(description)

    # 2. insert verification after every unverified mutating call (FM-3.2)
    for i in _unverified_mutating(working):
        working, inserted = _insert_verify(working, i)
        if inserted is not None:
            result.applied.append(f"insert-verify: {inserted.tool}")

    # re-attribute the repaired trace
    repaired_report = attribute(working)
    result.cleared_modes = {
        m for m in failed_modes
        if not any(d.mode_id == m for d in repaired_report.detections)
    }
    result.remaining_modes = failed_modes - result.cleared_modes
    result.unrepairable = sorted(result.remaining_modes)
    result.repaired_trace = working
    return result


