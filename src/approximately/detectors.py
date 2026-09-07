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

from .trace import ERROR, MESSAGE, PLAN, RESPONSE, TOOL_CALL, Trace

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


class NoTerminationDetector:
    """FM-1.5 Unaware of Termination — the run does not know when to stop.

    Two mechanical signatures, both low-false-positive:

    (a) the same (tool, args) action recurs 3+ times with a spread wider
        than the repeat-detector window — a long-range loop the agent
        never concluded;
    (b) the run declared a ``meta["step_limit"]`` and hit it while still
        planning/acting — the budget cut it off mid-flight.
    """

    min_recurrences = 3
    long_range_span = 6  # beyond RepeatDetector's window

    def detect(self, trace: Trace) -> Optional[Detection]:
        by_fp: dict = {}
        for step in trace.steps:
            if step.kind == TOOL_CALL and not step.error:
                by_fp.setdefault(step.fingerprint(), []).append(step.index)

        for fp, indexes in by_fp.items():
            if (len(indexes) >= self.min_recurrences
                    and indexes[-1] - indexes[0] > self.long_range_span):
                return Detection(
                    "FM-1.5",
                    indexes[-1],
                    [
                        f"same action executed at steps {indexes}",
                        f"spread of {indexes[-1] - indexes[0]} steps exceeds the "
                        f"local repeat window — a loop the agent never concluded",
                        "the task was already satisfiable at the first occurrence",
                    ],
                    0.65,
                    source="rule:NoTerminationDetector",
                )

        step_limit = trace.meta.get("step_limit")
        if (isinstance(step_limit, int) and len(trace.steps) >= step_limit
                and trace.steps and trace.steps[-1].kind != RESPONSE):
            return Detection(
                "FM-1.5",
                trace.steps[-1].index,
                [
                    f"step limit {step_limit} reached while still "
                    f"{trace.steps[-1].kind}",
                    "the run never reached a termination decision",
                ],
                0.6,
                source="rule:NoTerminationDetector",
            )
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


_INTENT_RE = None


def _intent_tool(thought: str) -> Optional[str]:
    """Extract 'will call <tool>' style announced tool names from a thought."""
    global _INTENT_RE
    if _INTENT_RE is None:
        import re

        _INTENT_RE = re.compile(
            r"\b(?:will|now|then|let'?s|next)\s+"
            r"(?:call|use|run|invoke|execute)\s+`?([a-z_][a-z0-9_]{2,})`?",
            re.IGNORECASE,
        )
    match = _INTENT_RE.search(thought)
    return match.group(1).lower() if match else None


class ReasoningActionMismatchDetector:
    """FM-2.6 Reasoning-Action Mismatch — the agent announced one tool but
    executed another.

    Fires only on explicit intent statements ("will call book_flight") where
    the announced name is a plausible tool (underscore, or seen elsewhere in
    the trace) and differs from the executed tool.
    """

    def detect(self, trace: Trace) -> Optional[Detection]:
        known = {s.tool for s in trace.steps if s.kind == TOOL_CALL and s.tool}
        for step in trace.steps:
            if step.kind != TOOL_CALL or not step.thought or not step.tool:
                continue
            announced = _intent_tool(step.thought)
            if not announced or announced == step.tool.lower():
                continue
            plausible = "_" in announced or announced in known
            if not plausible:
                continue
            return Detection(
                "FM-2.6",
                step.index,
                [
                    f"thought announced: “{step.thought[:80]}”",
                    f"actually executed: {step.tool}",
                    "stated reasoning does not match the action taken",
                ],
                0.65,
                source="rule:ReasoningActionMismatchDetector",
            )
        return None


class WeakVerificationDetector:
    """FM-3.3 Incorrect Verification — verification happened but proved
    nothing: it merely echoed the original claim instead of gathering
    independent evidence."""

    def detect(self, trace: Trace) -> Optional[Detection]:
        markers = MissingVerificationDetector.VERIFY_MARKERS
        for i, step in enumerate(trace.steps):
            if step.kind != TOOL_CALL or step.error or not step.meta.get("mutating"):
                continue
            for later in trace.steps[i + 1:]:
                is_verify = later.meta.get("verify") or (
                    later.kind == TOOL_CALL and later.tool and any(
                        m in later.tool.lower() for m in markers))
                if not is_verify:
                    continue
                claimed = " ".join(step.result.split()).lower()
                evidence = " ".join((later.error or later.result or "").split()).lower()
                if claimed and evidence and claimed == evidence:
                    return Detection(
                        "FM-3.3",
                        later.index,
                        [
                            f"verification step: {later.short()}",
                            f"echoes the original claim verbatim: “{claimed[:60]}”",
                            "no independent evidence was gathered — "
                            "the verification proved nothing",
                        ],
                        0.6,
                        source="rule:WeakVerificationDetector",
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


class ClarificationDetector:
    """FM-2.2 Fail to Ask for Clarification — the task was ambiguous, no
    question was ever asked, and the agent committed to an irreversible
    action anyway."""

    def detect(self, trace: Trace) -> Optional[Detection]:
        task = trace.task.lower()
        ambiguous = (" or " in task and ("?" in task or "either" in task)) or \
            trace.meta.get("ambiguous")
        if not ambiguous:
            return None
        asked = any(
            "?" in (s.thought or "") or "?" in (s.result or "")
            for s in trace.steps
        )
        if asked:
            return None
        committed = next(
            (s for s in trace.steps if s.kind == TOOL_CALL and s.meta.get("mutating")),
            None,
        )
        target = committed or (trace.steps[-1] if trace.steps else None)
        if target is None:
            return None
        return Detection(
            "FM-2.2",
            target.index,
            [
                f"task is ambiguous: “{trace.task[:80]}”",
                "no step in the run ever asks the user anything",
                f"agent committed to: {target.short(width=60)}",
            ],
            0.55,
            source="rule:ClarificationDetector",
        )


class WithholdingDetector:
    """FM-2.4 Information Withholding — a tool result flagged
    ``meta["share_with"]`` was never sent via a message to the agents that
    needed it, yet those agents kept acting."""

    def detect(self, trace: Trace) -> Optional[Detection]:
        for i, step in enumerate(trace.steps):
            share_with = step.meta.get("share_with")
            if step.kind != TOOL_CALL or not share_with:
                continue
            owner = step.meta.get("agent", "unknown")
            sent = any(
                s.kind == MESSAGE and s.meta.get("from_agent") == owner
                for s in trace.steps[i + 1:]
            )
            if sent:
                continue
            acted = [
                s for s in trace.steps[i + 1:]
                if s.kind in (TOOL_CALL, PLAN)
                and s.meta.get("agent") in share_with
            ]
            if acted:
                return Detection(
                    "FM-2.4",
                    i,
                    [
                        f"agent '{owner}' produced: {step.short(width=60)}",
                        f"flagged share_with={share_with} but never messaged them",
                        f"agent(s) {', '.join(sorted(set(share_with)))} acted on "
                        f"stale state afterwards",
                    ],
                    0.6,
                    source="rule:WithholdingDetector",
                )
        return None


class IgnoredInputDetector:
    """FM-2.5 Ignored Other Agent's Input — a delivered message never
    produced any downstream action by its recipient."""

    def detect(self, trace: Trace) -> Optional[Detection]:
        for i, step in enumerate(trace.steps):
            if step.kind != MESSAGE:
                continue
            recipient = step.meta.get("to_agent")
            if not recipient or step.meta.get("requires_ack") is not True:
                continue
            downstream = [
                s for s in trace.steps[i + 1:]
                if s.meta.get("agent") == recipient and s.kind != MESSAGE
            ]
            if not downstream:
                return Detection(
                    "FM-2.5",
                    i,
                    [
                        f"message delivered: {step.tool} "
                        f"“{(step.result or '')[:60]}”",
                        f"recipient '{recipient}' never acted on it "
                        "(requires_ack was set)",
                    ],
                    0.65,
                    source="rule:IgnoredInputDetector",
                )
        return None


ALL_DETECTORS = [
    RepeatDetector(),
    NoTerminationDetector(),
    ConversationResetDetector(),
    PrematureTerminationDetector(),
    MissingVerificationDetector(),
    WeakVerificationDetector(),
    ReasoningActionMismatchDetector(),
    DerailmentDetector(),
    SpecViolationDetector(),
    ClarificationDetector(),
    WithholdingDetector(),
    IgnoredInputDetector(),
]


def run_rules(trace: Trace) -> List[Detection]:
    """Run every rule detector; returns detections sorted by confidence."""
    found = [d for d in (det.detect(trace) for det in ALL_DETECTORS) if d]
    return sorted(found, key=lambda d: -d.confidence)


def args_hash(args: dict) -> str:
    blob = json.dumps(args, sort_keys=True, default=str)
    return hashlib.sha1(blob.encode()).hexdigest()[:10]
