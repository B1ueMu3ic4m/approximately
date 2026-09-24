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
    runner_ups: List[dict] = field(default_factory=list)

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
            "runner_ups": self.runner_ups,
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


def _arbitrate(detections: List, verdict) -> Optional[str]:
    """Fuse a judge verdict into the rule detections in place.

    Agreement boosts the top rule's confidence; disagreement appends the
    judge's own detection and returns a human-readable disagreement note.
    """
    rule_top = detections[0] if detections else None
    if rule_top and rule_top.mode_id == verdict.detection.mode_id:
        rule_top.confidence = min(0.99, rule_top.confidence + CONFIRM_BONUS)
        rule_top.evidence.extend(verdict.detection.evidence)
        return None
    detections.append(verdict.detection)
    if rule_top is None:
        return None
    return (
        f"rules say {rule_top.mode_id} "
        f"({rule_top.confidence:.2f}), judge says "
        f"{verdict.detection.mode_id} "
        f"({verdict.detection.confidence:.2f})"
    )


def _runner_ups(meaningful: List, primary_id: str,
                limit: int = 2) -> List[dict]:
    """Runner-up hypotheses after the primary verdict.

    Attribution is a ranking, not an oracle: these are the other modes
    the detectors actually fired for, with their strongest evidence.
    """
    groups: Dict[str, List] = {}
    for det in meaningful:
        if det.mode_id != primary_id:
            groups.setdefault(det.mode_id, []).append(det)
    ranked = sorted(
        groups.items(),
        key=lambda kv: (-max(d.confidence for d in kv[1]), len(kv[1])),
    )
    return [
        {
            "mode": mode_id,
            "label": get_mode(mode_id).label,
            "detections": len(dets),
            "max_confidence": round(max(d.confidence for d in dets), 2),
        }
        for mode_id, dets in ranked[:limit]
    ]


def _verdict_summary(failed: bool, meaningful: List) -> tuple:
    """Pick the primary mode and the one-line summary for the report."""
    if not failed and not meaningful:
        return get_mode(OTHER), \
            "No failure detected: run succeeded and no rule detector fired."
    if not meaningful:
        return get_mode(OTHER), (
            "Run failed, but no MAST mode reached the confidence floor. "
            "Try `approximately attribute --judge` for semantic classification."
        )
    primary = get_mode(meaningful[0].mode_id)
    where = f" at step #{meaningful[0].step_index}" if failed else ""
    return primary, f"{primary.label}{where}: {primary.definition}"


def attribute(trace: Trace, use_judge: bool = False,
              min_confidence: Optional[float] = None,
              **judge_kwargs) -> FailureReport:
    """Produce a FailureReport for *trace*.

    ``use_judge=True`` adds the LLM verdict; when the judge is unavailable
    (no openai package, no API key, network error) attribution silently
    degrades to rules-only — attribution must never hard-fail.
    ``min_confidence`` raises the per-detection admission floor above
    the built-in 0.5 for noisy environments; it never lowers it.
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
            disagreement = _arbitrate(detections, verdict)

    floor = MIN_CONFIDENCE if min_confidence is None \
        else max(MIN_CONFIDENCE, float(min_confidence))
    meaningful = [d for d in detections if d.confidence >= floor]
    meaningful = fuse_evidence(meaningful)
    primary, summary = _verdict_summary(failed, meaningful)

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
        runner_ups=_runner_ups(meaningful, primary.id),
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


def explain_fusion(detections: List[Detection]) -> str:
    """Human-readable account of the Bayesian fusion ranking.

    For each detection: the MAST base-rate prior (as log-odds), the
    log-likelihood-ratio its confidence contributes, and the fused
    score that determines the order — so a verdict can be audited as
    arithmetic, not vibes. Detections below the confidence floor are
    shown as excluded, with the reason.
    """
    import math

    if not detections:
        return "no detections to explain"
    priors = mast_priors()
    lines = ["fusion ranking (score = prior log-odds + sum of LLR):"]
    scores: Dict[str, float] = {}
    prior_odds: Dict[str, float] = {}
    for det in detections:
        if det.mode_id not in scores:
            prior = priors.get(det.mode_id, 1.0 / UNIFORM_PRIOR)
            prior_odds[det.mode_id] = math.log(prior * UNIFORM_PRIOR)
            scores[det.mode_id] = prior_odds[det.mode_id]
        scores[det.mode_id] += _llr(det.confidence)
        lines.append(
            f"  {det.mode_id} [{det.source}] conf {det.confidence:.2f}: "
            f"prior(p={priors.get(det.mode_id, 1.0 / UNIFORM_PRIOR):.3f}, "
            f"log-odds {prior_odds[det.mode_id]:+.2f})"
            f" + LLR {_llr(det.confidence):+.2f}"
            f" = {scores[det.mode_id]:+.2f}  (step #{det.step_index})"
        )
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    lines.append("  => verdict: " + " > ".join(m for m, _ in ranked))
    return "\n".join(lines)


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
