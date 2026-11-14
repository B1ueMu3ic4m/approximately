"""Trace data model: the unit of evidence in Approximately.

A :class:`Trace` is a recorded agent run — an ordered list of :class:`Step`
objects plus outcome metadata. Everything downstream (detectors, judge,
replayer, regression generator) consumes traces; the recorder produces them.

Traces are plain dataclasses serializable to/from JSON with no dependencies.
"""

from __future__ import annotations

import dataclasses
import json
import math
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, cast

# Step kinds, kept as a small closed vocabulary so detectors can rely on them.
PLAN = "plan"
TOOL_CALL = "tool_call"
OBSERVATION = "observation"
RESPONSE = "response"
ERROR = "error"
MESSAGE = "message"

STEP_KINDS = (PLAN, TOOL_CALL, OBSERVATION, RESPONSE, ERROR, MESSAGE)


def coerce_epoch(value: Any) -> float:
    """``created_at`` as a float the math can use — 0.0 when a
    foreign record carries a string, None, or a non-finite lie.
    Hand-edited and imported traces must never crash a fleet
    surface; a zeroed timestamp sorts oldest and says so."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    v = float(value)
    return v if math.isfinite(v) else 0.0


def coerce_count(value: Any, cap: int = 10_000_000) -> int:
    """A step counter (tokens, latency) as a clamped int: 0 when
    a foreign record carries a non-numeric or negative lie, and
    capped so ``float(counter)`` can never overflow the math
    downstream (a 10**400-token line is a lie, not a number)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    try:
        v = float(value)
    except OverflowError:
        # a 10**400 int cannot even become a float: cap the lie
        return cap
    if not (math.isfinite(v) and v >= 0):
        return 0
    return min(int(v), cap)


def _coerce_success(value: Any) -> "bool | None":
    """The verdict as the record promised it: JSON true/false and
    the numeric 1/0 become bools, the strings "true"/"false"
    (hand-edited files, foreign exports) become bools, and
    anything else is unknown — never a truthy lie that retires
    failure evidence on the success clock."""
    if isinstance(value, str):
        return {"true": True, "false": False}.get(
            value.strip().lower())
    if value in (0, 1) and not isinstance(value, bool):
        return bool(value)
    return value if isinstance(value, bool) else None


def _text_or_none(value: Any) -> "str | None":
    """A name as the record promised it: None stays None (the
    CSV contract pins the blank), a hostile scalar becomes its
    string, a string stays itself."""
    if value is None or isinstance(value, str):
        return value
    return str(value)


def _coerce_step_fields(raw: Dict[str, Any]) -> None:
    """Coerce one foreign step record's fields in place: counters
    clamp, dicts stay dicts, names stay names. Identity for the
    recorder's own well-typed records; a refusal-to-lie for
    everything else."""
    _coerce_step_counters(raw)
    _coerce_step_shapes(raw)


def _coerce_step_counters(raw: Dict[str, Any]) -> None:
    for key in ("tokens", "latency_ms", "index"):
        if key in raw:
            raw[key] = coerce_count(raw[key])


def _coerce_step_shapes(raw: Dict[str, Any]) -> None:
    for key in ("args", "meta"):
        if key in raw and not isinstance(raw[key], dict):
            raw[key] = {}
    for key in ("kind", "tool", "result", "agent"):
        value = raw.get(key)
        if value is not None and not isinstance(value, str):
            raw[key] = str(value)


@dataclass
class Step:
    """One recorded action or event inside an agent run."""

    kind: str
    tool: Optional[str] = None
    args: Dict[str, Any] = field(default_factory=dict)
    result: str = ""
    thought: Optional[str] = None
    tokens: int = 0
    latency_ms: int = 0
    error: Optional[str] = None
    index: int = 0
    meta: Dict[str, Any] = field(default_factory=dict)
    agent: Optional[str] = None

    def fingerprint(self) -> str:
        """Stable identity of *what* this step did, ignoring its outcome.

        Used by the repeat detector: two tool calls with the same tool and
        arguments have the same fingerprint regardless of result or timing.
        """
        args_blob = json.dumps(self.args, sort_keys=True, default=str)
        return f"{self.kind}:{self.tool}:{args_blob}"

    def short(self, width: int = 72) -> str:
        head = self.tool or self.kind
        text = self.error or self.result or self.thought or ""
        text = " ".join(text.split())
        if len(text) > width:
            text = text[: width - 3] + "..."
        return f"#{self.index} [{self.kind}] {head}: {text}"

    def to_dict(self) -> Dict[str, Any]:
        data = dataclasses.asdict(self)
        # The integrity chain hashes this dict: omitting the unset agent
        # keeps pre-agent records byte-identical, so their stored chains
        # still verify. Agent identity on stamped steps is chain-covered.
        if data.get("agent") is None:
            data.pop("agent", None)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Step":
        """Foreign records are coerced, not trusted: counters
        clamp, dicts stay dicts, names stay names — one hostile
        JSONL line must arrive as a usable step, not a TypeError
        waiting in every downstream command."""
        if not isinstance(data, dict):
            raise ValueError("step record must be a JSON object")
        known = {f.name for f in dataclasses.fields(cls)}
        raw = {k: v for k, v in data.items() if k in known}
        _coerce_step_fields(raw)
        return cls(**raw)


@dataclass
class Trace:
    """A recorded agent run."""

    task: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: float = field(default_factory=time.time)
    model: str = "unknown"
    steps: List[Step] = field(default_factory=list)
    success: Optional[bool] = None
    final_output: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def add(self, step: Step) -> Step:
        step.index = len(self.steps)
        self.steps.append(step)
        return step

    def tool_calls(self, tool: Optional[str] = None) -> List[Step]:
        return [
            s
            for s in self.steps
            if s.kind == TOOL_CALL and (tool is None or s.tool == tool)
        ]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "task": self.task,
            "created_at": self.created_at,
            "model": self.model,
            "success": self.success,
            "final_output": self.final_output,
            "meta": self.meta,
            "steps": [s.to_dict() for s in self.steps],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Trace":
        if not isinstance(data, dict):
            raise ValueError("trace record must be a JSON object")
        steps_data = data.get("steps", [])
        if not isinstance(steps_data, list):
            raise ValueError("malformed trace: 'steps' must be a list")
        meta = data.get("meta", {})
        if not isinstance(meta, dict):
            meta = {}
        trace = cls(
            # _text_or_none: None stays None (the CSV contract
            # pins the blank), a hostile scalar becomes a string
            # cast: None rides at runtime (the CSV contract
            # pins the blank); the annotation stays str
            task=cast("str", _text_or_none(data.get("task", ""))),
            id=data.get("id", uuid.uuid4().hex[:12]),
            # coerce_epoch is the contract: hand-edited and
            # imported traces must never crash a fleet surface
            created_at=coerce_epoch(data.get("created_at", 0.0)),
            model=cast("str", _text_or_none(
                data.get("model", "unknown"))),
            success=_coerce_success(data.get("success")),
            final_output=data.get("final_output"),
            meta=meta,
        )
        trace.steps = [Step.from_dict(s) for s in steps_data]
        # index is POSITIONAL truth: a foreign record with
        # non-sequential indexes (5, 6 for two steps) sent the
        # repeat detector indexing past the end of the list in
        # every attribution consumer
        for i, step in enumerate(trace.steps):
            step.index = i
        return trace

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    @classmethod
    def from_json(cls, text: str) -> "Trace":
        return cls.from_dict(json.loads(text))
