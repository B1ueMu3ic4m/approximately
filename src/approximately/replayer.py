"""Replayer: re-run a recorded trajectory and diff it against the recording.

An :term:`Executor` is any callable ``Callable[[Step], str]`` that performs a
recorded step and returns its result text (raise to record an error). Replays
answer the postmortem question "does this still happen?" and enable A/B
comparison between the original executor and a patched one.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .trace import TOOL_CALL, Step, Trace

Executor = Callable[[Step], str]

REPRODUCED = "reproduced"
DIVERGED = "diverged"
CONSISTENT = "consistent"


@dataclass
class StepDiff:
    index: int
    kind: str
    tool: Optional[str]
    recorded: str
    replayed: str
    error: Optional[str]
    similarity: float
    match: bool

    @property
    def headline(self) -> str:
        head = self.tool or self.kind
        if self.error:
            return f"#{self.index} {head}: ERROR {self.error}"
        if not self.match:
            return (
                f"#{self.index} {head}: diverged "
                f"(similarity {self.similarity:.2f})"
            )
        return f"#{self.index} {head}: ok"


@dataclass
class ReplayDiff:
    trace_id: str
    steps: List[StepDiff] = field(default_factory=list)
    match_rate: float = 0.0
    verdict: str = CONSISTENT

    def summary(self) -> str:
        lines = [
            f"replay {self.trace_id}: {self.verdict} "
            f"({sum(1 for s in self.steps if s.match)}/{len(self.steps)} steps match)"
        ]
        lines += ["  " + s.headline for s in self.steps if not s.match]
        return "\n".join(lines)


def _similarity(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def replay(
    trace: Trace,
    executor: Executor,
    threshold: float = 0.85,
    only_tool_calls: bool = True,
) -> ReplayDiff:
    """Re-execute every recorded step through *executor* and diff results.

    Steps whose execution raises are recorded as errors on that step and make
    the replay diverge. ``verdict`` is ``reproduced`` when a step that errored
    in the recording errors again at the same index, ``consistent`` when all
    steps match, ``diverged`` otherwise.
    """
    diffs: List[StepDiff] = []
    reproduced_failure = False
    all_match = True

    for step in trace.steps:
        if only_tool_calls and step.kind != TOOL_CALL:
            continue
        try:
            value = executor(step)
            error = None
        except Exception as exc:  # noqa: BLE001 - replay must capture any failure
            value = ""
            error = f"{type(exc).__name__}: {exc}"
        recorded_text = step.error or step.result
        similarity = _similarity(recorded_text, value if error is None else "")
        match = error is None and similarity >= threshold
        if step.error and error is not None:
            reproduced_failure = True
            match = True  # same failure at the same step = faithful replay
        if not match:
            all_match = False
        diffs.append(
            StepDiff(
                index=step.index,
                kind=step.kind,
                tool=step.tool,
                recorded=recorded_text,
                replayed=value if error is None else error,
                error=error,
                similarity=similarity,
                match=match,
            )
        )

    match_rate = (sum(1 for d in diffs if d.match) / len(diffs)) if diffs else 1.0
    if reproduced_failure:
        verdict = REPRODUCED
    elif all_match:
        verdict = CONSISTENT
    else:
        verdict = DIVERGED
    return ReplayDiff(trace_id=trace.id, steps=diffs,
                      match_rate=match_rate, verdict=verdict)
