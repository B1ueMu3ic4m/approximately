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
fewer than `min_samples` calls, or a truly uniform sample (every
value identical — no scale information), yield no anomalies rather
than made-up ones.  A merely *flat-majority* baseline (ms-rounded
latencies make MAD == 0 common) falls back to the mean absolute
deviation: a flat baseline is exactly where an outlier is most
obvious, so that is the last place to go blind.

The same ruler measures a second meter: **tokens**.  Latency catches
the call that ran long; token burn catches the call that worked too
hard — the receipt a retry loop or a context-stuffing derailment
leaves behind even when every call came back quickly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .trace import TOOL_CALL, Step, Trace

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


def _scale(values: List[float], med: float) -> float:
    """Robust scale for the modified z-score: MAD when it has
    scale, else the mean absolute deviation.

    MAD == 0 whenever the majority of samples is identical — ms-
    rounded latencies make that common, and a perfectly flat
    baseline is where an outlier is most obvious.  Only true
    uniformity (every sample equal) returns 0 and stays a no-op.
    """
    mad = _median([abs(v - med) for v in values])
    if mad > 0:
        return mad
    return sum(abs(v - med) for v in values) / len(values)


@dataclass
class TraceLatencyAnomaly:
    """A fleet-mode finding: the anomaly carries its trace."""

    trace_id: str
    step_index: int
    tool: str
    latency_ms: int
    median_ms: float
    robust_z: float

    @property
    def direction(self) -> str:
        return "slow" if self.robust_z > 0 else "fast"


def detect_fleet_anomalies(traces: list, threshold: float
                           = MODIFIED_Z_THRESHOLD,
                           min_samples: int = 5
                           ) -> List[TraceLatencyAnomaly]:
    """Per-tool latency baselines across a whole store.

    A per-trace baseline only knows what this one run considered
    normal; the fleet knows what `search` costs everywhere, every
    day. Every timed tool-call step in every trace is judged against
    its tool family's store-wide median/MAD; families under
    ``min_samples`` are honest no-ops.
    """
    by_tool: dict = {}
    for trace in traces:
        for step in trace.steps:
            if step.kind == TOOL_CALL and step.latency_ms                     and step.latency_ms > 0:
                by_tool.setdefault(step.tool or "?", []).append(
                    (trace, step))
    anomalies: List[TraceLatencyAnomaly] = []
    for tool, pairs in sorted(by_tool.items()):
        if len(pairs) < min_samples:
            continue
        values = [float(s.latency_ms) for _, s in pairs]
        med = _median(values)
        mad = _scale(values, med)
        if mad == 0:
            continue  # identical latencies: no scale, no anomalies
        for trace, step in pairs:
            z = _CONSISTENCY * (float(step.latency_ms) - med) / mad
            if abs(z) > threshold:
                anomalies.append(TraceLatencyAnomaly(
                    trace_id=trace.id,
                    step_index=step.index,
                    tool=tool,
                    latency_ms=step.latency_ms,
                    median_ms=med,
                    robust_z=round(z, 2),
                ))
    anomalies.sort(key=lambda a: -abs(a.robust_z))
    return anomalies


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
        mad = _scale(values, med)
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
            mad = _scale(values, med)
            if mad == 0:
                continue  # identical latencies: no scale
            anomalies.extend(_flagged(steps, values, med, mad,
                                      threshold))
            continue
        # rare tool: judge its own latencies against the pooled scale
        values = [float(s.latency_ms) for s in timed]
        med = _median(values)
        mad = _scale(values, med)
        if mad == 0:
            continue  # every sample identical: no scale, no anomalies
        family = [float(s.latency_ms) for s in steps]
        anomalies.extend(_flagged(steps, family, med, mad, threshold))
    anomalies.sort(key=lambda a: -abs(a.robust_z))
    return anomalies



def _flagged(timed: list, values: list, med: float, mad: float,
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


# ------------------------------------------------------------- tokens
#
# The same ruler, a different meter.  Latency catches the call that
# ran long; token burn catches the call that *worked too hard* — the
# receipt a retry loop or a context-stuffing derailment leaves behind
# even when every call came back quickly.


@dataclass
class TokenAnomaly:
    step_index: int
    tool: str
    tokens: int
    median_tokens: float
    robust_z: float

    @property
    def direction(self) -> str:
        return "burn" if self.robust_z > 0 else "frugal"


@dataclass
class TraceTokenAnomaly:
    """A fleet-mode token finding: the anomaly carries its trace."""

    trace_id: str
    step_index: int
    tool: str
    tokens: int
    median_tokens: float
    robust_z: float

    @property
    def direction(self) -> str:
        return "burn" if self.robust_z > 0 else "frugal"


@dataclass
class ResultAnomaly:
    step_index: int
    tool: str
    result_chars: int
    median_chars: float
    robust_z: float

    @property
    def direction(self) -> str:
        return "bloat" if self.robust_z > 0 else "concise"


@dataclass
class TraceResultAnomaly:
    """A fleet-mode result-length finding: it carries its trace."""

    trace_id: str
    step_index: int
    tool: str
    result_chars: int
    median_chars: float
    robust_z: float

    @property
    def direction(self) -> str:
        return "bloat" if self.robust_z > 0 else "concise"


def _result_steps(trace: Trace) -> List:
    """Tool-call steps whose result text is non-empty: the candidates
    for the context-composition meter.  Non-string results are data
    lies — the meters skip them instead of crashing on len()."""
    return [s for s in trace.steps
            if s.kind == TOOL_CALL and isinstance(s.result, str)
            and s.result]


def detect_result_anomalies(trace: Trace,
                            threshold: float = MODIFIED_Z_THRESHOLD,
                            min_samples: int = 5
                            ) -> List[ResultAnomaly]:
    """Flag tool results whose character length is a robust outlier.

    The third meter (after latency and tokens): a tool that dumps a
    40k-character wall into the context is a context-composition
    problem no token count isolates — the tokens may be cheap while
    the window fills.  Same modified z-score ruler; only tool-call
    steps with non-empty results are measured."""
    metered = _result_steps(trace)
    if len(metered) < min_samples:
        return []
    values = [float(len(s.result)) for s in metered]
    med = _median(values)
    mad = _scale(values, med)
    if mad == 0:
        return []  # identical lengths: no scale
    anomalies = []
    for step, value in zip(metered, values):
        z = _CONSISTENCY * (value - med) / mad
        if abs(z) > threshold:
            anomalies.append(ResultAnomaly(
                step_index=step.index,
                tool=step.tool or "?",
                result_chars=len(step.result),
                median_chars=med,
                robust_z=round(z, 2),
            ))
    anomalies.sort(key=lambda a: -abs(a.robust_z))
    return anomalies


def detect_fleet_result_anomalies(traces: list,
                                  threshold: float
                                  = MODIFIED_Z_THRESHOLD
                                  ) -> List[TraceResultAnomaly]:
    """Result-length outliers across the whole store (fleet view)."""
    out: List[TraceResultAnomaly] = []
    for trace in traces:
        out.extend(
            TraceResultAnomaly(
                trace_id=trace.id,
                step_index=a.step_index,
                tool=a.tool,
                result_chars=a.result_chars,
                median_chars=a.median_chars,
                robust_z=a.robust_z,
            )
            for a in detect_result_anomalies(trace,
                                             threshold=threshold))
    out.sort(key=lambda a: -abs(a.robust_z))
    return out


def summarize_result_anomalies(anomalies: List[ResultAnomaly]) -> str:
    """One line for the anomalies door."""
    if not anomalies:
        return "no result-length outliers"
    worst = anomalies[0]
    return (f"{len(anomalies)} result-length outlier(s); worst: "
            f"step #{worst.step_index} {worst.tool} "
            f"{worst.result_chars:,} chars "
            f"(median {worst.median_chars:,.0f}, "
            f"z={worst.robust_z:+.1f}, {worst.direction})")


def _metered_steps(trace: Trace) -> List:
    """Tool-call steps that carry a positive token count."""
    return [s for s in trace.steps
            if s.kind == TOOL_CALL and s.tokens and s.tokens > 0]


def detect_token_anomalies(trace: Trace, threshold: float
                           = MODIFIED_Z_THRESHOLD,
                           min_samples: int = 5,
                           per_tool: bool = False
                           ) -> List[TokenAnomaly]:
    """Flag per-step token counts whose modified z-score exceeds
    threshold.  Same robust ruler as the latency family; only
    tool-call steps that report tokens are measured."""
    metered = _metered_steps(trace)
    if len(metered) < min_samples:
        return []
    if not per_tool:
        values = [float(s.tokens) for s in metered]
        med = _median(values)
        mad = _scale(values, med)
        if mad == 0:
            return []  # identical token counts: no scale
        return _flagged_tokens(metered, values, med, mad, threshold)
    by_tool: dict = {}
    for step in metered:
        by_tool.setdefault(step.tool or "?", []).append(step)
    anomalies: List[TokenAnomaly] = []
    for _tool, steps in sorted(by_tool.items()):
        if len(steps) >= min_samples:
            values = [float(s.tokens) for s in steps]
            med = _median(values)
            mad = _scale(values, med)
            if mad == 0:
                continue
            anomalies.extend(_flagged_tokens(steps, values, med, mad,
                                             threshold))
            continue
        # rare tool: judge against the run's pooled token scale
        values = [float(s.tokens) for s in metered]
        med = _median(values)
        mad = _scale(values, med)
        if mad == 0:
            continue  # every sample identical: no scale, no anomalies
        family = [float(s.tokens) for s in steps]
        anomalies.extend(_flagged_tokens(steps, family, med, mad,
                                         threshold))
    anomalies.sort(key=lambda a: -abs(a.robust_z))
    return anomalies



def _flagged_tokens(metered: list, values: list, med: float,
                    mad: float,
                    threshold: float) -> List[TokenAnomaly]:
    anomalies = []
    for step, value in zip(metered, values):
        z = _CONSISTENCY * (value - med) / mad
        if abs(z) > threshold:
            anomalies.append(TokenAnomaly(
                step_index=step.index,
                tool=step.tool or "?",
                tokens=step.tokens,
                median_tokens=med,
                robust_z=round(z, 2),
            ))
    anomalies.sort(key=lambda a: -abs(a.robust_z))
    return anomalies


def detect_fleet_token_anomalies(traces: list, threshold: float
                                 = MODIFIED_Z_THRESHOLD,
                                 min_samples: int = 5,
                                 per_model: bool = False
                                 ) -> List[TraceTokenAnomaly]:
    """Per-tool token baselines across a whole store — the fleet
    knows what `search` should cost in tokens everywhere, every
    day; families under ``min_samples`` are honest no-ops.

    ``per_model`` splits each tool family by the trace's model: a
    gpt-4o and a mini doing the "same" search are different scale
    rulers, and pooling them hides both ends."""
    def family_key(trace: Trace, step: Step) -> tuple:
        if per_model:
            return (step.tool or "?", str(trace.model or "unknown"))
        return (step.tool or "?",)

    by_family: dict = {}
    for trace in traces:
        for step in _metered_steps(trace):
            by_family.setdefault(family_key(trace, step), []).append(
                (trace, step))
    anomalies: List[TraceTokenAnomaly] = []
    for key, pairs in sorted(by_family.items(), key=repr):
        if len(pairs) < min_samples:
            continue
        values = [float(s.tokens) for _, s in pairs]
        med = _median(values)
        mad = _scale(values, med)
        if mad == 0:
            continue
        tool = key[0]
        model = key[1] if per_model else None
        for trace, step in pairs:
            z = _CONSISTENCY * (float(step.tokens) - med) / mad
            if abs(z) > threshold:
                anomalies.append(TraceTokenAnomaly(
                    trace_id=trace.id,
                    step_index=step.index,
                    tool=(f"{tool} [{model}]" if model else tool),
                    tokens=step.tokens,
                    median_tokens=med,
                    robust_z=round(z, 2),
                ))
    anomalies.sort(key=lambda a: -abs(a.robust_z))
    return anomalies


def summarize_token_anomalies(anomalies: List[TokenAnomaly]) -> str:
    if not anomalies:
        return "no token anomalies"
    med = anomalies[0].median_tokens
    lines = [(f"{len(anomalies)} token anomaly/anomalies "
              f"(median {med:.0f} tokens):")]
    lines.extend(
        f"  step #{a.step_index} {a.tool}: {a.tokens} tokens "
        f"({a.direction}, z={a.robust_z})"
        for a in anomalies
    )
    return "\n".join(lines)
