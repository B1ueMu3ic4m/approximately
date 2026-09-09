"""Attribution orchestrator: rules + optional judge -> one FailureReport.

Arbitration policy:
- rule and judge agree on the mode  -> confidence is boosted (capped at 0.99)
- they disagree                     -> the higher-confidence side wins and the
  disagreement is recorded on the report so users can see both readings.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .detectors import Detection, run_rules
from .judge import JudgeError, judge_trace
from .taxonomy import FAILURE_MODES, OTHER, FailureMode, get_mode
from .trace import Trace


@dataclass
class FailureReport:
    """The postmortem verdict for one trace."""

    trace_id: str
    task: str
    failed: bool
    primary_mode: FailureMode
    detections: List[Detection] = field(default_factory=list)
    judge_used: bool = False
    disagreement: Optional[str] = None
    suggested_fixes: List[str] = field(default_factory=list)
    summary: str = ""

    @property
    def category_label(self) -> str:
        return self.primary_mode.label

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "task": self.task,
            "failed": self.failed,
            "primary_mode": self.primary_mode.id,
            "summary": self.summary,
            "judge_used": self.judge_used,
            "disagreement": self.disagreement,
            "suggested_fixes": self.suggested_fixes,
            "detections": [
                {
                    "mode_id": d.mode_id,
                    "step_index": d.step_index,
                    "confidence": round(d.confidence, 3),
                    "source": d.source,
                    "evidence": d.evidence,
                }
                for d in self.detections
            ],
        }


CONFIRM_BONUS = 0.1
MIN_CONFIDENCE = 0.5


def attribute(trace: Trace, use_judge: bool = False, **judge_kwargs) -> FailureReport:
    """Produce a FailureReport for *trace*.

    ``use_judge=True`` adds the LLM verdict; when the judge is unavailable
    (no openai package, no API key, network error) attribution silently
    degrades to rules-only — attribution must never hard-fail.
    """
    failed = trace.success is False
    detections = run_rules(trace)
    judge_used = False
    disagreement: Optional[str] = None

    if use_judge:
        try:
            verdict = judge_trace(trace, **judge_kwargs)
        except JudgeError:
            # Attribution must never hard-fail: degrade to rules-only.
            pass
        else:
            judge_used = True
            rule_top = detections[0] if detections else None
            if rule_top and rule_top.mode_id == verdict.detection.mode_id:
                rule_top.confidence = min(0.99, rule_top.confidence + CONFIRM_BONUS)
                rule_top.evidence.extend(verdict.detection.evidence)
            else:
                detections.append(verdict.detection)
                if rule_top is not None:
                    disagreement = (
                        f"rules say {rule_top.mode_id} "
                        f"({rule_top.confidence:.2f}), judge says "
                        f"{verdict.detection.mode_id} "
                        f"({verdict.detection.confidence:.2f})"
                    )

    meaningful = [d for d in detections if d.confidence >= MIN_CONFIDENCE]
    meaningful = fuse_evidence(meaningful)

    if not failed and not meaningful:
        primary = get_mode(OTHER)
        summary = "No failure detected: run succeeded and no rule detector fired."
    elif not meaningful:
        primary = get_mode(OTHER)
        summary = (
            "Run failed, but no MAST mode reached the confidence floor. "
            "Try `approximately attribute --judge` for semantic classification."
        )
    else:
        primary = get_mode(meaningful[0].mode_id)
        where = f" at step #{meaningful[0].step_index}" if failed else ""
        summary = f"{primary.label}{where}: {primary.definition}"

    return FailureReport(
        trace_id=trace.id,
        task=trace.task,
        failed=failed,
        primary_mode=primary,
        detections=meaningful,
        judge_used=judge_used,
        disagreement=disagreement,
        suggested_fixes=list(primary.fixes),
        summary=summary,
    )


# ---- Bayesian evidence fusion (v0.3.2) --------------------------------------
#
# The naive "highest confidence wins" rule throws away information: it cannot
# express that two weak independent detections of the same mode accumulate,
# and it ignores everything MAST taught us about base rates (FM-1.3 alone is
# 17% of all failures).
#
# fuse() implements log-likelihood-ratio (LLR) Bayesian fusion:
#
#     score(m) = ln( prior(m) / uniform )            # base-rate prior, as odds
#              + sum over detections d voting m of
#                ln( (c_d + eps) / (1 - c_d + eps) )  # evidence LLR
#
# Confidence maps through a smoothed logit, so c=0 is evidence *against* the
# mode (not zero evidence) and c=1 is bounded, never infinite. Independent
# detections accumulate additively in log space; the MAST share acts as the
# base-rate prior expressed as log-odds against a uniform distribution, so a
# strong detection can still outrank a rare-mode prior.

EPS = 0.005         # Laplace-style smoothing bound
UNIFORM_PRIOR = 14  # number of MAST modes


def mast_priors() -> Dict[str, float]:
    """MAST base rates as priors, add-one smoothed so every mode is positive.

    Modes with published shares get their rate + 1 pseudo-count; unrated
    modes get just the pseudo-count — rare, but never zero (log(0) is
    undefined and no mode should be a priori impossible).
    """
    shares = {m.id: (m.mast_share or 0.0)
              for m in FAILURE_MODES.values() if m.id != OTHER}
    smoothed = {k: v + 1.0 for k, v in shares.items()}
    total = sum(smoothed.values())
    return {k: v / total for k, v in smoothed.items()}


def _llr(confidence: float) -> float:
    """Log-likelihood ratio of a detection voting for a mode."""
    return math.log((confidence + EPS) / (1 - confidence + EPS))


def score_modes(trace: Trace) -> Dict[str, float]:
    """Fusion score of EVERY MAST mode for a trace (unfiltered, unranked).

    prior-odds + summed LLR of all detections, per mode — the raw score
    surface that fuse_evidence ranks and calibration/conformal consume.
    """
    detections = run_rules(trace)
    priors = mast_priors()
    scores: Dict[str, float] = {}
    for mode_id, prior in priors.items():
        scores[mode_id] = math.log(prior * UNIFORM_PRIOR)
    for det in detections:
        if det.mode_id in scores:
            scores[det.mode_id] += _llr(det.confidence)
    return scores


def fuse_evidence(detections: List[Detection]) -> List[Detection]:
    """Re-rank detections by Bayesian score: MAST prior odds + summed LLR.

    Returns the same Detection objects, best mode first. Ties break toward
    the higher base-rate mode.
    """
    priors = mast_priors()
    scores: Dict[str, float] = {}
    for det in detections:
        prior = priors.get(det.mode_id, 1.0 / UNIFORM_PRIOR)
        prior_odds = math.log(prior * UNIFORM_PRIOR)
        scores[det.mode_id] = scores.get(det.mode_id, 0.0) + _llr(det.confidence)
        scores[det.mode_id] += prior_odds
    return sorted(detections, key=lambda d: -scores[d.mode_id])
