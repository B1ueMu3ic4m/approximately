"""Behavior-drift detection: Population Stability Index over actions.

When a prompt, model version, or tool changes, agent behavior shifts —
and nobody notices until failures spike. PSI (Population Stability Index)
compares the action distribution of a recent window against a baseline:

    PSI = sum_i (a_i - b_i) * ln(a_i / b_i)

with add-smoothing so empty buckets never divide by zero. Industry
convention: PSI < 0.1 no shift, 0.1-0.25 moderate, > 0.25 significant.
The buckets here are action structure tokens (kind:tool {arg-keys}) from
``align.normalize_step`` — the same shape vocabulary the aligner uses.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Tuple

from .align import normalize_step
from .trace import Trace

EPS = 1e-6  # smoothing for empty buckets

NO_SHIFT = "no shift"
MODERATE = "moderate shift"
SIGNIFICANT = "significant shift"


def _counts(traces: Iterable[Trace]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    total = 0
    for trace in traces:
        for step in trace.steps:
            if step.kind == "tool_call" and not step.error:
                token = normalize_step(step)[1]  # structure token
                counts[token] = counts.get(token, 0) + 1
                total += 1
    counts["__total__"] = total
    return counts


@dataclass
class DriftReport:
    psi: float
    verdict: str
    baseline_actions: int
    current_actions: int
    top_shifted: List[Tuple[str, float, float]] = field(default_factory=list)
    # (action, baseline share, current share) — biggest absolute moves first

    def summary(self) -> str:
        lines = [(f"PSI {self.psi:.3f} [{self.verdict}] "
                  f"(baseline {self.baseline_actions} actions vs "
                  f"current {self.current_actions})")]
        for action, base, cur in self.top_shifted:
            lines.append(f"  {action[:50]}: {base:.1%} -> {cur:.1%}")
        return "\n".join(lines)


def population_stability(baseline_counts: Dict[str, int],
                         current_counts: Dict[str, int]) -> Tuple[float, List]:
    base_total = max(1, baseline_counts.get("__total__", 0))
    cur_total = max(1, current_counts.get("__total__", 0))
    actions = (set(baseline_counts) | set(current_counts)) - {"__total__"}
    psi = 0.0
    moved: List[Tuple[str, float, float]] = []
    for action in actions:
        a = (baseline_counts.get(action, 0) + EPS) / (base_total + EPS)
        b = (current_counts.get(action, 0) + EPS) / (cur_total + EPS)
        psi += (a - b) * math.log(a / b)
        moved.append((action, a, b))
    moved.sort(key=lambda t: -abs(t[1] - t[2]))
    return psi, moved


def detect_drift(baseline_traces: Iterable[Trace],
                 current_traces: Iterable[Trace]) -> DriftReport:
    base_counts = _counts(baseline_traces)
    cur_counts = _counts(current_traces)
    base_total = base_counts.get("__total__", 0)
    cur_total = cur_counts.get("__total__", 0)
    psi, moved = population_stability(base_counts, cur_counts)
    if psi < 0.1:
        verdict = NO_SHIFT
    elif psi <= 0.25:
        verdict = MODERATE
    else:
        verdict = SIGNIFICANT
    top = [(action, base, cur) for action, base, cur in moved[:5]]
    return DriftReport(psi=psi, verdict=verdict,
                       baseline_actions=base_total,
                       current_actions=cur_total, top_shifted=top)
