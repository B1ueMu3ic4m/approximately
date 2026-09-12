"""Streaming reliability monitor: live failure-risk for agents in flight.

Batch postmortems explain runs that already failed. This module watches
agent runs **while they execute**: after every step it fuses three
independent statistical signals into one live risk estimate and fires
escalations at deterministic thresholds.

Signals (each individually tested, fused by simple weighted voting with
hysteresis so risk cannot flap):

1. **precursor** — n-gram early-warning probability from the historical
   store (precursor.py), evaluated on the action prefix so far
2. **repetition velocity** — identical-action recurrence rate over a
   sliding window (the FM-1.3 signature, live)
3. **verification debt** — mutating calls with no subsequent verify in
   the window (the FM-3.2 signature, live)

This is the streaming half of the reliability stack: the same statistics
that power postmortems, computed incrementally, with an API an agent
loop can call after every tool call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from .trace import TOOL_CALL, Step, Trace

VERIFY_MARKERS = ("verify", "check", "confirm", "get_", "read", "fetch",
                  "status")


class Level(Enum):
    NOMINAL = "nominal"
    WATCH = "watch"
    ELEVATED = "elevated"
    CRITICAL = "critical"


def _is_verify_step(step: Step) -> bool:
    if step.meta.get("verify"):
        return True
    if step.kind != TOOL_CALL or not step.tool:
        return False
    return any(m in step.tool.lower() for m in VERIFY_MARKERS)


@dataclass
class RiskState:
    """One monitoring observation after a step."""

    step_index: int
    risk: float                     # [0, 1]
    level: Level
    signals: Dict[str, float]       # per-signal contributions
    escalated: bool = False         # crossed its threshold this observation
    note: str = ""


@dataclass
class StreamingMonitor:
    """Incremental failure-risk estimator over an in-flight run.

    ``precursor_model`` is optional (precursor.PrecursorModel); without
    it only the two structural signals fire.
    """

    window: int = 6
    repetition_threshold: float = 2     # identical calls in window -> 1.0
    verification_debt_limit: int = 2    # unverified mutating calls -> 1.0
    precursor_weight: float = 0.5
    repetition_weight: float = 0.3
    verification_weight: float = 0.2
    watch_at: float = 0.3
    elevated_at: float = 0.55
    critical_at: float = 0.8
    hysteresis: float = 0.1  # required drop to leave a higher level
    precursor_model: Optional[object] = None
    _fingerprints: List[str] = field(default_factory=list)
    _unverified_open: int = 0
    _last_level: Level = Level.NOMINAL
    _risk_by_step: Dict[int, float] = field(default_factory=dict)

    # -- signals ---------------------------------------------------------
    def _repetition_velocity(self, step: Step) -> float:
        fp = step.fingerprint()
        self._fingerprints.append(fp)
        self._fingerprints = self._fingerprints[-self.window:]
        occurrences = self._fingerprints.count(fp)
        if occurrences <= 1:
            return 0.0
        return min(1.0, (occurrences - 1) / max(1, self.repetition_threshold))

    def _verification_debt(self, step: Step) -> float:
        if step.kind == TOOL_CALL and step.meta.get("mutating"):
            self._unverified_open += 1
        elif _is_verify_step(step):
            self._unverified_open = max(0, self._unverified_open - 1)
        return min(1.0, self._unverified_open
                   / max(1, self.verification_debt_limit))

    def _precursor_signal(self, trace: Trace) -> float:
        if self.precursor_model is None:
            return 0.0
        score = self.precursor_model.probability(trace)  # type: ignore[attr-defined]
        return (score.probability - 0.5) * 2  # center: 0.5 -> 0

    # -- level machine ------------------------------------------------------
    def _level_for(self, risk: float) -> Level:
        # hysteresis first: leaving a higher level requires dropping below
        # (threshold - hysteresis), so risk cannot flap around a threshold
        higher = self._last_level
        floor = {Level.WATCH: self.watch_at - self.hysteresis,
                 Level.ELEVATED: self.elevated_at - self.hysteresis,
                 Level.CRITICAL: self.critical_at - self.hysteresis}
        if higher == Level.CRITICAL and risk >= floor[Level.CRITICAL]:
            return Level.CRITICAL
        if (higher in (Level.CRITICAL, Level.ELEVATED)
                and risk >= floor[Level.ELEVATED]):
            return Level.ELEVATED
        if higher == Level.WATCH and risk >= floor[Level.WATCH]:
            return Level.WATCH
        if risk >= self.critical_at:
            return Level.CRITICAL
        if risk >= self.elevated_at:
            return Level.ELEVATED
        if risk >= self.watch_at:
            return Level.WATCH
        return Level.NOMINAL

    # -- main entry ----------------------------------------------------------
    def observe(self, trace: Trace) -> RiskState:
        """Recompute risk after the latest step of *trace*.

        Call after every tool call; the monitor is incremental, so this is
        O(window) per observation regardless of trace length.
        """
        steps = trace.steps
        if not steps:
            return RiskState(step_index=-1, risk=0.0, level=Level.NOMINAL,
                             signals={})
        latest = steps[-1]
        signals: Dict[str, float] = {}

        repetition = self._repetition_velocity(latest)
        signals["repetition"] = repetition
        debt = self._verification_debt(latest)
        signals["verification_debt"] = debt
        precursor = self._precursor_signal(trace)
        signals["precursor"] = precursor

        risk = min(1.0, repetition * self.repetition_weight
                   + debt * self.verification_weight
                   + max(0.0, precursor) * self.precursor_weight)

        level = self._level_for(risk)
        escalated = (level.value in ("elevated", "critical")
                     and level != self._last_level)
        self._last_level = level
        self._risk_by_step[latest.index] = risk
        return RiskState(step_index=latest.index, risk=risk, level=level,
                         signals=signals, escalated=escalated)

    def risk_curve(self) -> List[Tuple[int, float]]:
        return sorted(self._risk_by_step.items())
