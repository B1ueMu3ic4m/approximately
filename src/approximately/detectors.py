"""Rule-based failure detectors.

Each detector scans a :class:`~approximately.trace.Trace` for the mechanical
signature of one MAST failure mode and returns a :class:`Detection` with a
human-readable evidence chain. Detectors run without any LLM, so attribution
works offline, deterministically, and for free; the optional LLM judge
(:mod:`approximately.judge`) complements them for semantic modes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import List, Optional

from .trace import ERROR, PLAN, RESPONSE, TOOL_CALL, Trace

STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "of", "for", "with", "from", "by",
    "on", "in", "at", "is", "are", "be", "that", "this", "it", "as", "then",
}


@dataclass
class Detection:
    """One detector firing (or a judge verdict) on a trace."""

    mode_id: str
    step_index: int
    evidence: List[str] = field(default_factory=list)
    confidence: float = 0.5
    source: str = "rule"

    @property
    def where(self) -> str:
        return f"step #{self.step_index}"


def _join(texts: List[str]) -> str:
    return " ".join(t for t in texts if t).lower()


def _task_keywords(trace: Trace) -> List[str]:
    words = "".join(c if c.isalnum() else " " for c in trace.task.lower()).split()
    return [w for w in words if len(w) > 3 and w not in STOPWORDS]


class RepeatDetector:
    """FM-1.3 Step Repetition — same (tool, args) called again within a window."""

    window = 6
    min_repeats = 2

    def detect(self, trace: Trace) -> Optional[Detection]:
        seen: dict = {}
        for step in trace.steps:
            if step.kind != TOOL_CALL or step.error:
                continue
            fp = step.fingerprint()
            if fp in seen and step.index - seen[fp] <= self.window:
                count = sum(
                    1
                    for s in trace.steps[seen[fp]: step.index + 1]
                    if s.fingerprint() == fp
                )
                evidence = [
                    f"first call: {trace.steps[seen[fp]].short()}",
                    f"repeated call: {step.short()}",
                    f"{count} identical calls within a {self.window}-step window",
                ]
                conf = min(0.95, 0.6 + 0.1 * count)
                return Detection("FM-1.3", step.index, evidence, conf,
                                 source="rule:RepeatDetector")
            seen[fp] = step.index
        return None


class ConversationResetDetector:
    """FM-2.1 Conversation Reset — the seed prompt reappears mid-run."""

    def detect(self, trace: Trace) -> Optional[Detection]:
        seed = trace.task.strip().lower()
        if not seed:
            return None
        for step in trace.steps[1:]:
            if step.kind == PLAN and step.thought and step.thought.strip().lower() == seed:
                return Detection(
                    "FM-2.1",
                    step.index,
                    [
                        f"task prompt: “{trace.task[:80]}”",
                        f"re-issued verbatim at {step.short()}",
                        "progress made before this step was implicitly discarded",
                    ],
                    0.75,
                    source="rule:ConversationResetDetector",
                )
        return None


class PrematureTerminationDetector:
    """FM-3.1 — run failed and the agent stopped without a repair attempt."""

    def detect(self, trace: Trace) -> Optional[Detection]:
        if trace.success is not False:
            return None
        if not trace.steps:
            return None
        last = trace.steps[-1]

        # Claimed completion but the harness marked the run failed.
        if last.kind == RESPONSE:
            return Detection(
                "FM-3.1",
                last.index,
                [
                    f"final response: {last.short()}",
                    "run marked failed (trace.success = False)",
                    "no goal-completion checklist was evaluated before terminating",
                ],
                0.7,
                source="rule:PrematureTerminationDetector",
            )

        if last.kind == ERROR:
            error_idx = last.index
            repairs = [
                s
                for s in trace.steps[error_idx + 1:]
                if s.kind in (TOOL_CALL, PLAN)
            ]
            if not repairs:
                return Detection(
                    "FM-3.1",
                    error_idx,
                    [
                        f"error: {last.short()}",
                        "run terminated immediately after the error",
                        f"{len(trace.steps) - error_idx - 1} steps followed — none was a repair attempt",
                    ],
                    0.8,
                    source="rule:PrematureTerminationDetector",
                )
        return None


class MissingVerificationDetector:
    """FM-3.2 — a mutating action is never followed by a verification step."""

    VERIFY_MARKERS = ("verify", "check", "confirm", "get_", "read", "fetch", "status")

    def detect(self, trace: Trace) -> Optional[Detection]:
        for i, step in enumerate(trace.steps):
            if step.kind != TOOL_CALL or step.error:
                continue
            if not step.meta.get("mutating"):
                continue
            verified = False
            for later in trace.steps[i + 1:]:
                if later.meta.get("verify"):
                    verified = True
                    break
                if later.kind == TOOL_CALL and later.tool and any(
                    m in later.tool.lower() for m in self.VERIFY_MARKERS
                ):
                    verified = True
                    break
            if not verified:
                return Detection(
                    "FM-3.2",
                    i,
                    [
                        f"mutating call: {step.short()} (meta.mutating=true)",
                        "no verification step anywhere after it",
                        "errors from mutating calls propagate silently to the final answer",
                    ],
                    0.7,
                    source="rule:MissingVerificationDetector",
                )
        return None


class DerailmentDetector:
    """FM-2.3 Task Derailment — most tool activity ignores the task's keywords.

    Heuristic on purpose: it is a cheap recall net. The LLM judge should be
    used to confirm or reject its verdict.
    """

    min_calls = 3
    relevance_floor = 0.3

    def detect(self, trace: Trace) -> Optional[Detection]:
        keywords = set(_task_keywords(trace))
        calls = trace.tool_calls()
        if len(calls) < self.min_calls or not keywords:
            return None
        irrelevant = []
        for step in calls:
            text = _join(
                [step.tool or "", json.dumps(step.args, default=str)]
            )
            if not any(k in text for k in keywords):
                irrelevant.append(step)
        ratio = len(irrelevant) / len(calls)
        if ratio >= 1 - self.relevance_floor * 2 and ratio >= 0.5:
            evidence = [
                f"task keywords: {', '.join(sorted(keywords)[:8])}",
                f"{len(irrelevant)}/{len(calls)} tool calls touch none of them, e.g. "
                + "; ".join(s.short(width=48) for s in irrelevant[:2]),
            ]
            return Detection(
                "FM-2.3",
                irrelevant[0].index,
                evidence,
                min(0.55, 0.35 + ratio * 0.2),
                source="rule:DerailmentDetector",
            )
        return None


class SpecViolationDetector:
    """FM-1.1 Disobey Task Specification — a declared-forbidden tool is used.

    Requires ``trace.meta["forbidden_tools"]`` (the task spec's prohibitions).
    """

    def detect(self, trace: Trace) -> Optional[Detection]:
        forbidden = trace.meta.get("forbidden_tools") or []
        for step in trace.steps:
            if step.kind == TOOL_CALL and step.tool in forbidden:
                return Detection(
                    "FM-1.1",
                    step.index,
                    [
                        f"task spec forbids tools: {', '.join(forbidden)}",
                        f"used anyway: {step.short()}",
                    ],
                    0.9,
                    source="rule:SpecViolationDetector",
                )
        return None


ALL_DETECTORS = [
    RepeatDetector(),
    ConversationResetDetector(),
    PrematureTerminationDetector(),
    MissingVerificationDetector(),
    DerailmentDetector(),
    SpecViolationDetector(),
]


def run_rules(trace: Trace) -> List[Detection]:
    """Run every rule detector; returns detections sorted by confidence."""
    found = [d for d in (det.detect(trace) for det in ALL_DETECTORS) if d]
    return sorted(found, key=lambda d: -d.confidence)


def args_hash(args: dict) -> str:
    blob = json.dumps(args, sort_keys=True, default=str)
    return hashlib.sha1(blob.encode()).hexdigest()[:10]
