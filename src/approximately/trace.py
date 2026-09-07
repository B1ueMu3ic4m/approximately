"""Trace data model: the unit of evidence in Approximately.

A :class:`Trace` is a recorded agent run — an ordered list of :class:`Step`
objects plus outcome metadata. Everything downstream (detectors, judge,
replayer, regression generator) consumes traces; the recorder produces them.

Traces are plain dataclasses serializable to/from JSON with no dependencies.
"""

from __future__ import annotations

import dataclasses
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Step kinds, kept as a small closed vocabulary so detectors can rely on them.
PLAN = "plan"
TOOL_CALL = "tool_call"
OBSERVATION = "observation"
RESPONSE = "response"
ERROR = "error"
MESSAGE = "message"

STEP_KINDS = (PLAN, TOOL_CALL, OBSERVATION, RESPONSE, ERROR, MESSAGE)


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
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Step":
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


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
        trace = cls(
            task=data["task"],
            id=data.get("id", uuid.uuid4().hex[:12]),
            created_at=data.get("created_at", 0.0),
            model=data.get("model", "unknown"),
            success=data.get("success"),
            final_output=data.get("final_output"),
            meta=data.get("meta", {}),
        )
        trace.steps = [Step.from_dict(s) for s in data.get("steps", [])]
        return trace

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    @classmethod
    def from_json(cls, text: str) -> "Trace":
        return cls.from_dict(json.loads(text))
