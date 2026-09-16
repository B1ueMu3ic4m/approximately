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
                             min_samples: int = 5) -> List[LatencyAnomaly]:
    """Flag per-step latencies whose modified z-score exceeds threshold.

    Only tool-call steps are measured (plans/observations carry no
    meaningful latency). Returns anomalies sorted by |z| descending.
    """
    timed = [s for s in trace.steps
             if s.kind == TOOL_CALL and s.latency_ms and s.latency_ms > 0]
    if len(timed) < min_samples:
        return []
    values = [float(s.latency_ms) for s in timed]
    med = _median(values)
    mad = _mad(values, med)
    if mad == 0:
        return []  # identical latencies: no scale, no anomalies
    return _flagged(timed, values, med, mad, threshold)


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
