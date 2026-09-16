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


def _shingles(text: str, k: int = 3) -> set:
    normalized = " ".join(text.lower().split())
    return {normalized[i:i + k]
            for i in range(0, max(1, len(normalized) - k + 1))}


def _jaccard(a: set, b: set) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


class ProseRestartDetector:
    """FM-2.1 in prose: the run starts over.

    Three shapes, by definition of a trajectory restart:
    - the agent's own **opening turn re-occurs** later near-verbatim
      (SequenceMatcher >= 0.9) — the planner starts from scratch;
    - the opening turn re-occurs as a **shingle-overlap paraphrase**
      (character-trigram Jaccard >= 0.5) — same subject re-derived in
      different words, order-tolerant where SequenceMatcher is not;
    - the task statement is re-stated verbatim inside a later turn.
    """

    restart_similarity = 0.9
    restart_jaccard = 0.5
    min_opening = 40  # chars for an opening turn to be distinctive
    min_shingle_len = 80  # Jaccard on shorter texts is noise
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
        opening_shingles = _shingles(opening)
        for idx in range(self.first_progress_position, len(turns)):
            candidate = turns[idx]
            if SequenceMatcher(None, opening, candidate).ratio() \
                    >= self.restart_similarity:
                return self._detection(idx, candidate, "near-verbatim",
                                        0.75)
            jaccard = _jaccard(opening_shingles, _shingles(candidate)) \
                if len(candidate) >= self.min_shingle_len else 0.0
            if jaccard >= self.restart_jaccard:
                # 0.7: majority-trigram overlap on long turns is
                # evidence of the same strength as near-verbatim
                # repetition - and it must clear the 0.7 rules-labeler
                # floor to be usable as a prediction at all
                return self._detection(idx, candidate,
                                       f"as a shingle-overlap paraphrase "
                                       f"(J={jaccard:.2f})", 0.7)
        return None

    def _detection(self, idx: int, turn: str, shape: str,
                   confidence: float) -> "object":
        from .detectors import Detection

        return Detection(
            "FM-2.1", idx,
            [(f"the run's opening turn re-occurs {shape} at position "
              f"{idx} — the agent restarted its approach instead of "
              "progressing"),
             f"recurring text: \"{turn[:100]}\""],
            confidence,
            source="rule:ProseRestartDetector",
        )

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


_IDENTIFIER = re.compile(
    r"`?[A-Za-z_][A-Za-z0-9_]{2,}(?:\.[A-Za-z_][A-Za-z0-9_]*)+`?"
    r"|`[^`]{3,60}`")


class ProseThoughtActionDetector:
    """FM-2.6 in prose: the stated thought and the taken action diverge.

    HyperAgent-style turns carry both halves in one message
    ("Thought: ... Action: ..."). The thought's distinctive entities
    (dotted identifiers, quoted names — method/file/class references)
    are what the agent *claims* to work on; if at least two such
    entities exist and NONE of them appears in the action half, the
    stated plan and the executed step have parted ways.
    """

    min_entities = 2

    @staticmethod
    def _halves(turn: str) -> Optional[tuple]:
        lowered = turn.lower()
        tpos = lowered.find("thought:")
        apos = lowered.find("action:")
        if tpos == -1 or apos == -1 or apos <= tpos:
            return None
        return turn[tpos + 8:apos], turn[apos + 7:]

    def detect(self, trace: Trace) -> Optional["object"]:
        for step in trace.steps:
            if step.kind != TOOL_CALL or not step.result:
                continue
            turn = " ".join(step.result.split())
            halves = self._halves(turn)
            if halves is None:
                continue
            thought, action = halves
            entities = {e.strip("`") for e in
                        _IDENTIFIER.findall(thought)}
            if len(entities) < self.min_entities:
                continue
            if any(e in action for e in entities):
                continue
            from .detectors import Detection

            return Detection(
                "FM-2.6",
                step.index,
                [(f"thought names {sorted(entities)[:3]} but the action "
                  "half references none of them — stated plan and "
                  "executed step have diverged"),
                 f"action: \"{action[:100]}\""],
                0.55,
                source="rule:ProseThoughtActionDetector",
            )
        return None


PROSE_DETECTORS: List[Any] = [
    ProseRepeatDetector(),
    ProseRestartDetector(),
    ProseDerailmentDetector(),
    ProseNoVerifyDetector(),
    ProseAmbiguityDetector(),
    ProseThoughtActionDetector(),
]
