"""Prose-level failure detectors for chat-shaped trajectories.

The tool-call detectors fingerprint *actions* (repeated (tool, args)
pairs, unverified mutating calls). Chat-shaped runs — the annotated
MAST corpus (arXiv:2503.13657), or any agent whose trace is message
turns — have no tool-call structure to fingerprint, so v0.13's real
benchmark scored 0.00. This family reads the *prose* instead.

Activation: traces converted from message trajectories carry
``trace.meta["prose"]`` (``mastdata`` sets it); ``run_rules`` runs this
family only then, so tool-shaped traces never see prose heuristics.

Thresholds are a priori, not fitted on the benchmark: near-verbatim
similarity at 0.92 (SequenceMatcher on normalized turns), keyword-loss
over the trailing window, marker vocabularies taken from the failure
definitions themselves. They are recall nets — the fusion layer treats
every detector as one evidence source, and the judge (or a human) is
the arbiter. All detectors return None unless the shape supports the
verdict; absence of evidence stays absence.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, List, Optional

from .mastdata import HARNESS_PREFIXES
from .trace import TOOL_CALL, Trace

_SIMILARITY = 0.92
_INSUFFICIENCY = (
    "insufficient", "not specified", "cannot be solved", "unclear",
    "more context", "not enough information", "missing information",
    "cannot be determined",
)
_NUDGE = re.compile(r"\b(continue|go on|keep (going|solving)|proceed)\b",
                    re.IGNORECASE)
_VERIFICATION = re.compile(
    r"\b(verif|check(ed)?|confirm|validate|test(ed)?|re-?run|assert)\w*\b",
    re.IGNORECASE)


def _is_harness(turn: str) -> bool:
    """AG2 math-proxy interrogator boilerplate, not agent behaviour."""
    lowered = turn.lower()
    return any(lowered.startswith(p) for p in HARNESS_PREFIXES)


def _turns(trace: Trace) -> List[str]:
    """Normalized agent-turn texts, harness boilerplate removed."""
    return [" ".join(step.result.split()) for step in trace.steps
            if step.kind == TOOL_CALL and step.result
            and not _is_harness(" ".join(step.result.split()))]


def _first_turns(trace: Trace) -> List[str]:
    """Normalized user-turn texts (converted plan steps)."""
    return [" ".join((s.thought or "").split())
            for s in trace.steps if s.thought]


class ProseRepeatDetector:
    """FM-1.3 in prose: near-verbatim assistant turns repeated."""

    min_turns = 4

    def detect(self, trace: Trace) -> Optional["object"]:
        turns = _turns(trace)
        if len(turns) < self.min_turns:
            return None
        for i in range(len(turns)):
            for j in range(i + 1, len(turns)):
                if SequenceMatcher(None, turns[i], turns[j]).ratio() \
                        >= _SIMILARITY:
                    return self._detection(i, j, turns)
        return None

    def _detection(self, i: int, j: int, turns: List[str]):
        from .detectors import Detection

        return Detection(
            "FM-1.3", j,
            [(f"assistant turn #{i} and #{j} are near-verbatim "
              f"({len(turns[i])} chars each): "
              f"\"{turns[j][:80]}\"")],
            0.7,
            source="rule:ProseRepeatDetector",
        )


class ProseRestartDetector:
    """FM-2.1 in prose: the run starts over.

    Two shapes, by definition of a trajectory restart:
    - the agent's own **opening turn re-occurs** later (near-verbatim)
      — the planner starts the approach from scratch;
    - the task statement is re-stated verbatim inside a later turn.
    """

    restart_similarity = 0.9
    min_opening = 40  # chars for an opening turn to be distinctive
    first_progress_position = 3  # recurrences before this are warm-up

    def detect(self, trace: Trace) -> Optional["object"]:
        turns = _turns(trace)
        hit = None
        if len(turns) >= self.first_progress_position + 1:
            hit = self._opening_recurrence(turns)
        return hit or self._task_restated(trace, turns)

    def _opening_recurrence(self, turns: List[str]) -> Optional["object"]:
        opening = turns[0]
        if len(opening) < self.min_opening:
            return None
        from .detectors import Detection

        for idx in range(self.first_progress_position, len(turns)):
            if SequenceMatcher(None, opening, turns[idx]).ratio() \
                    >= self.restart_similarity:
                return Detection(
                    "FM-2.1", idx,
                    [(f"the run's opening turn re-occurs near-verbatim "
                      f"at position {idx} — the agent restarted its "
                      "approach instead of progressing"),
                     f"recurring text: \"{turns[idx][:100]}\""],
                    0.75,
                    source="rule:ProseRestartDetector",
                )
        return None

    def _task_restated(self, trace: Trace,
                       turns: List[str]) -> Optional["object"]:
        task = " ".join(trace.task.split()).lower()
        if len(task) < 40:
            return None
        for idx, turn in enumerate(turns):
            if task[:200] in turn.lower():
                from .detectors import Detection

                return Detection(
                    "FM-2.1", idx,
                    [("task statement re-stated verbatim inside an "
                      f"assistant turn at position {idx} — the run is "
                      "restarting instead of progressing"),
                     f"re-stated text: \"{turn[:100]}\""],
                    0.6,
                    source="rule:ProseRestartDetector",
                )
        return None


class ProseDerailmentDetector:
    """FM-2.3 in prose: task keywords vanish from the trailing turns."""

    min_turns = 5
    trailing = 3

    @staticmethod
    def _keywords(task: str) -> set:
        return set(re.findall(r"[a-z']{4,}", task.lower()))

    def detect(self, trace: Trace) -> Optional["object"]:
        turns = _turns(trace)
        if len(turns) < self.min_turns:
            return None
        keywords = self._keywords(trace.task)
        if not keywords:
            return None
        head_hits = any(k in t.lower() for k in keywords
                        for t in turns[:len(turns) // 2])
        tail = turns[-self.trailing:]
        tail_hits = sum(1 for t in tail
                        if any(k in t.lower() for k in keywords))
        if head_hits and tail_hits == 0:
            from .detectors import Detection

            return Detection(
                "FM-2.3", len(turns) - self.trailing,
                [(f"none of the last {self.trailing} assistant turns "
                  f"touch any task keyword "
                  f"({', '.join(sorted(keywords)[:6])}...) "
                  "while earlier turns did"),
                 f"last turn: \"{turns[-1][:100]}\""],
                0.55,
                source="rule:ProseDerailmentDetector",
            )
        return None


class ProseNoVerifyDetector:
    """FM-3.2 in prose: a conclusion is produced, verification never."""

    min_turns = 4

    def detect(self, trace: Trace) -> Optional["object"]:
        turns = _turns(trace)
        if len(turns) < self.min_turns:
            return None
        if any(_VERIFICATION.search(t) for t in turns):
            return None
        from .detectors import Detection

        return Detection(
            "FM-3.2", len(turns) - 1,
            [(f"{len(turns)} assistant turns reach conclusions with no "
              "verification language anywhere in the run "
              "(no check/confirm/validate/test/verify)"),
             f"final turn: \"{turns[-1][:100]}\""],
            0.5,
            source="rule:ProseNoVerifyDetector",
        )


class ProseAmbiguityDetector:
    """FM-2.2 in prose: insufficiency named, then proceeded anyway."""

    def detect(self, trace: Trace) -> Optional["object"]:
        turns = _turns(trace)
        users = _first_turns(trace)
        flagged: Optional[int] = None
        for idx, text in enumerate(turns):
            lowered = text.lower()
            if any(m in lowered for m in _INSUFFICIENCY):
                flagged = idx
        if flagged is None:
            return None
        # a genuine clarification would be a question back to the user;
        # a nudge-and-continue means the agent walked past the gap
        asked = any(t.rstrip().endswith("?") for t in turns[flagged:])
        nudged = any(_NUDGE.search(u) for u in users)
        if asked or not nudged:
            return None
        from .detectors import Detection

        return Detection(
            "FM-2.2", flagged,
            [("assistant named the input as insufficient/ambiguous but, "
              "after a continue-nudge, answered without asking a "
              "clarifying question"),
             f"\"{turns[flagged][:100]}\""],
            0.6,
            source="rule:ProseAmbiguityDetector",
        )


PROSE_DETECTORS: List[Any] = [
    ProseRepeatDetector(),
    ProseRestartDetector(),
    ProseDerailmentDetector(),
    ProseNoVerifyDetector(),
    ProseAmbiguityDetector(),
]
