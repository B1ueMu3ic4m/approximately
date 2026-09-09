"""Counterfactual root-cause analysis: intervene on the trace, observe the
attribution.

Correlation between a detection and a step is cheap; causation requires an
experiment. For every detected step this module runs the do-operation
``do(step_i = ∅)`` — delete the step, re-run the full attribution — and
compares:

- **root cause**: the failure mode disappears when this step is removed
  (the step carries the failure)
- **symptom**: the mode persists without this step (the step is a
  consequence or a co-occurrence)
- **distributed cause**: no single removal kills the mode, but removing
  the whole cause-family does (e.g. 3 identical repeats — each alone is
  redundant, together they are the failure)

The result is a ranked table: remove these steps, in this order, and the
attributed failure disappears. Verified by replay afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .attributor import FailureReport, attribute
from .trace import Trace


def _without_step(trace: Trace, index: int) -> Trace:
    """A copy of *trace* with step *index* removed (do(step_i = ∅)).

    Steps are deep-copied: ``Trace.add`` re-assigns ``step.index``, and
    sharing Step objects with the original trace would silently renumber
    it — corrupting every later intervention.
    """
    from .trace import Step

    copy = Trace(task=trace.task, model=trace.model,
                 success=trace.success, meta=dict(trace.meta))
    for step in trace.steps:
        if step.index != index:
            copy.add(Step.from_dict(step.to_dict()))
    return copy


def _mode_present(report: FailureReport, mode_id: str) -> bool:
    return any(d.mode_id == mode_id for d in report.detections)


@dataclass
class Intervention:
    removed_step: int
    mode_id: str
    eliminated: bool          # mode gone after removing this step
    was_primary: bool         # mode was the report's primary before

    @property
    def label(self) -> str:
        role = "ROOT CAUSE" if self.eliminated else "symptom"
        return (f"step #{self.removed_step} -> {self.mode_id}: "
                f"{role}")


@dataclass
class CounterfactualReport:
    trace_id: str
    baseline_primary: str
    interventions: List[Intervention] = field(default_factory=list)
    distributed_causes: List[str] = field(default_factory=list)
    # steps whose removal eliminated the most failure modes, best first
    causal_ranking: List[int] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"baseline: {self.baseline_primary} · "
            f"{len(self.interventions)} interventions on trace {self.trace_id}"
        ]
        roots = [i for i in self.interventions if i.eliminated]
        if roots:
            lines.append("root-cause steps (removal eliminates the mode):")
            seen = set()
            for intervention in roots:
                key = (intervention.removed_step, intervention.mode_id)
                if key in seen:
                    continue
                seen.add(key)
                lines.append(f"  - {intervention.label}")
        if self.distributed_causes:
            lines.append("distributed causes (no single step suffices): "
                         + ", ".join(self.distributed_causes))
        if self.causal_ranking:
            lines.append("causal ranking by eliminated modes: "
                         + ", ".join(f"#{i}" for i in self.causal_ranking))
        return "\n".join(lines)


def counterfactual(trace: Trace) -> CounterfactualReport:
    """Leave-one-out attribution over every detected step."""
    baseline = attribute(trace)
    primary = baseline.primary_mode.id
    report = CounterfactualReport(trace_id=trace.id,
                                  baseline_primary=primary)

    detected_steps = sorted({d.step_index for d in baseline.detections})
    eliminated_modes_by_step: Dict[int, set] = {}

    for index in detected_steps:
        do_trace = _without_step(trace, index)
        do_report = attribute(do_trace)
        for det in baseline.detections:
            if det.step_index != index:
                continue
            eliminated = not _mode_present(do_report, det.mode_id)
            report.interventions.append(Intervention(
                removed_step=index, mode_id=det.mode_id,
                eliminated=eliminated,
                was_primary=(det.mode_id == primary)))
            eliminated_modes_by_step.setdefault(index, set())
            if eliminated:
                eliminated_modes_by_step[index].add(det.mode_id)

    # distributed causes: a mode that survives every single-step removal
    all_modes = {d.mode_id for d in baseline.detections}
    killed = set()
    for modes in eliminated_modes_by_step.values():
        killed |= modes
    report.distributed_causes = sorted(all_modes - killed - {"OTHER"})

    report.causal_ranking = sorted(
        eliminated_modes_by_step,
        key=lambda i: -len(eliminated_modes_by_step.get(i, set())),
    )
    return report
