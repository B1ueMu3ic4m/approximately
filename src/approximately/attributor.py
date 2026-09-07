"""Attribution orchestrator: rules + optional judge -> one FailureReport.

Arbitration policy:
- rule and judge agree on the mode  -> confidence is boosted (capped at 0.99)
- they disagree                     -> the higher-confidence side wins and the
  disagreement is recorded on the report so users can see both readings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .detectors import Detection, run_rules
from .judge import JudgeError, judge_trace
from .taxonomy import OTHER, FailureMode, get_mode
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
    meaningful.sort(key=lambda d: -d.confidence)

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
