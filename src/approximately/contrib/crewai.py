"""CrewAI adapter (best-effort, event-bus based).

CrewAI's event names and payloads move between releases; this adapter
registers defensively against whatever the installed version exposes::

    from approximately.contrib.crewai import record_crew

    with record_crew("quarterly report crew") as rec:
        crew.kickoff(inputs)
    report = attribute(rec.trace)

Requires ``crewai``; every handler is optional and failures to look up an
event type are ignored on purpose.
"""

from __future__ import annotations

from typing import Any, Optional

from ..recorder import Recorder


def _preview(value: Any, limit: int = 200) -> str:
    if value is None:
        return ""
    text = str(value)
    return " ".join(text.split())[:limit]


def _events_module():
    """Locate the event definitions across known crewai layouts."""
    try:
        import crewai_events as events  # standalone package layout

        return events
    except ImportError:
        pass
    try:
        from crewai.utilities import events as events  # bundled layout

        return events
    except ImportError:
        return None


def _event(name: str, events: Any) -> Optional[type]:
    return getattr(events, name, None)


class CrewAIRecorder:
    """Registers approximately recorders onto the CrewAI event bus."""

    def __init__(self, task: str):
        self.recorder = Recorder(task, model="crewai", save=False)
        self._handlers: list = []

    def register(self) -> None:
        events = _events_module()
        if events is None:
            return
        bus = getattr(events, "crewai_event_bus", None) or getattr(
            events, "EventBus", None
        )
        if bus is None:
            return

        register = getattr(bus, "register_handler", None) or getattr(
            bus, "on", None
        )
        if register is None:
            return

        def handler(event_name: str):
            def _inner(source: Any, payload: Any = None) -> None:
                self._on(event_name, source, payload)
            return _inner

        for name in (
            "ToolUsageFinished",
            "ToolUsageError",
            "LLMCallCompleted",
            "LLMCallFailed",
            "CrewKickoffCompleted",
            "CrewKickoffFailed",
        ):
            event_type = _event(name, events)
            if event_type is None:
                continue
            register(event_type, handler(name))
            self._handlers.append(name)

    def _on(self, event_name: str, source: Any, payload: Any) -> None:
        get = payload.get if isinstance(payload, dict) else (
            lambda key, default=None: getattr(payload, key, default)
        )
        if event_name == "ToolUsageFinished":
            self.recorder.tool(
                _preview(get("name", get("tool_name", "tool")), 60), {},
                result=_preview(get("output")),
            )
        elif event_name == "ToolUsageError":
            self.recorder.tool(
                _preview(get("name", get("tool_name", "tool")), 60), {},
                error=_preview(get("error")),
            )
        elif event_name == "LLMCallCompleted":
            self.recorder.plan(_preview(get("output", "")))
        elif event_name == "LLMCallFailed":
            self.recorder.tool("llm", {}, error=_preview(get("error")))
        elif event_name == "CrewKickoffFailed":
            self.recorder.fail(_preview(get("error", "crew kickoff failed")))
        # CrewKickoffCompleted: outcome owned by the caller (knows task success)


def record_crew(task: str) -> CrewAIRecorder:
    """Context-manager-free entry: register, kickoff your crew, then call
    ``rec.respond(...)`` and ``rec.report()``."""
    recorder = CrewAIRecorder(task)
    recorder.register()
    return recorder
