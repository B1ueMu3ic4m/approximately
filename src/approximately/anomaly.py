"""Robust latency-anomaly detection via the median absolute deviation.

A tool call that takes 40x its usual time is often the *first visible
symptom* of an agent going sideways: retries hidden behind a timeout,
a wedged dependency, a derailment loop hitting a slow path. Mean/std-dev
(standard z-score) is the wrong ruler — latencies are heavy-tailed and
the outliers are exactly what you are hunting, so they drag the mean
and inflate the sigma until they hide themselves.

The standard fix is the **modified z-score** (Iglewicz & Hoaglin 1993,
recommended threshold 3.5; the MAD itself is the most robust scale
estimator — see Leys et al. 2013, "Detecting outliers: Do not use
standard deviation around the mean, use median absolute deviation"):

    M_i = 0.6745 * (x_i - median) / MAD

computed over the steps of one trace. Degenerate cases are honest:
fewer than `min_samples` calls, or MAD == 0 (all samples identical —
no scale information), yield no anomalies rather than made-up ones.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .trace import TOOL_CALL, Trace

MODIFIED_Z_THRESHOLD = 3.5
_CONSISTENCY = 0.6745  # Phi^-1(3/4): median of the standard normal


@dataclass
class LatencyAnomaly:
    step_index: int
    tool: str
    latency_ms: int
    median_ms: float
    robust_z: float

    @property
    def direction(self) -> str:
        return "slow" if self.robust_z > 0 else "fast"


def _median(values: List[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _mad(values: List[float], med: float) -> float:
    return _median([abs(v - med) for v in values])


def detect_latency_anomalies(trace: Trace, threshold: float
                             = MODIFIED_Z_THRESHOLD,
                             min_samples: int = 5,
                             per_tool: bool = False
                             ) -> List[LatencyAnomaly]:
    """Flag per-step latencies whose modified z-score exceeds threshold.

    Only tool-call steps are measured (plans/observations carry no
    meaningful latency). Returns anomalies sorted by |z| descending.

    ``per_tool`` baselines each tool family separately: a trace that
    mixes 2-second searches with 30-second deploys pools them into one
    scale where neither looks anomalous. Families smaller than
    ``min_samples`` fall back to the pooled baseline rather than going
    blind on rare tools.
    """
    timed = [s for s in trace.steps
             if s.kind == TOOL_CALL and s.latency_ms and s.latency_ms > 0]
    if len(timed) < min_samples:
        return []
    if not per_tool:
        values = [float(s.latency_ms) for s in timed]
        med = _median(values)
        mad = _mad(values, med)
        if mad == 0:
            return []  # identical latencies: no scale, no anomalies
        return _flagged(timed, values, med, mad, threshold)
    by_tool: dict = {}
    for step in timed:
        by_tool.setdefault(step.tool or "?", []).append(step)
    anomalies: List[LatencyAnomaly] = []
    for _tool, steps in sorted(by_tool.items()):
        if len(steps) >= min_samples:
            values = [float(s.latency_ms) for s in steps]
            med = _median(values)
            mad = _mad(values, med)
            if mad == 0:
                continue  # identical latencies: no scale
            anomalies.extend(_flagged(steps, values, med, mad,
                                      threshold))
            continue
        # rare tool: judge its own latencies against the pooled scale
        values = [float(s.latency_ms) for s in timed]
        med = _median(values)
        mad = _mad(values, med)
        if mad == 0:
            anomalies.extend(_flag_zero_scale(steps, med))
            continue
        family = [float(s.latency_ms) for s in steps]
        anomalies.extend(_flagged(steps, family, med, mad, threshold))
    anomalies.sort(key=lambda a: -abs(a.robust_z))
    return anomalies


def _flag_zero_scale(steps, med: float) -> List[LatencyAnomaly]:
    """>50% identical steps leave no scale (MAD == 0); a rare call
    that differs from the median at all is then the anomaly
    (Iglewicz-Hoaglin: its z is unboundedly large)."""
    return [LatencyAnomaly(
        step_index=step.index,
        tool=step.tool or "?",
        latency_ms=step.latency_ms,
        median_ms=med,
        robust_z=9999.0 if step.latency_ms > med else -9999.0,
    ) for step in steps if float(step.latency_ms) != med]


def _flagged(timed, values, med: float, mad: float,
             threshold: float) -> List[LatencyAnomaly]:
    anomalies = []
    for step, value in zip(timed, values):
        z = _CONSISTENCY * (value - med) / mad
        if abs(z) > threshold:
            anomalies.append(LatencyAnomaly(
                step_index=step.index,
                tool=step.tool or "?",
                latency_ms=step.latency_ms,
                median_ms=med,
                robust_z=round(z, 2),
            ))
    anomalies.sort(key=lambda a: -abs(a.robust_z))
    return anomalies


def summarize_anomalies(anomalies: List[LatencyAnomaly]) -> str:
    if not anomalies:
        return "no latency anomalies"
    med = anomalies[0].median_ms
    lines = [(f"{len(anomalies)} latency anomaly/anomalies "
              f"(median {med:.0f}ms):")]
    lines.extend(
        f"  step #{a.step_index} {a.tool}: {a.latency_ms}ms "
        f"({a.direction}, z={a.robust_z})"
        for a in anomalies
    )
    return "\n".join(lines)
