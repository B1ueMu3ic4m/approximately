"""AutoGen adapter (best-effort, two capture seams).

AutoGen v0.4+ (``autogen-agentchat`` / ``autogen-core``) exposes two
instrumentation points and this adapter hooks both:

1. **Event log** — ``autogen_core.events`` publishes dataclass events
   (``LLMCallEvent``, ``FunctionCallEvent``, ``SelectSpeakerEvent``,
   ``TerminationEvent``, ...) through the standard :mod:`logging` module,
   the same seam AutoGen Studio consumes. A logging handler converts them::

       from approximately.contrib.autogen import record_autogen

       with record_autogen("triage ticket 42") as rec:
           await team.run(task="triage the ticket")
       report = attribute(rec.trace)

2. **Model client** — a transparent proxy around any
   ``ChatCompletionClient`` records every ``create()`` call directly at
   the model boundary, independent of logging config::

       from approximately.contrib.autogen import RecordingChatCompletionClient

       client = RecordingChatCompletionClient(OpenAIChatCompletionClient(...), rec)
       agent = AssistantAgent("a", model_client=client)

Both seams are version-tolerant by design: attribute lookups are defensive,
unknown events are ignored, and a handler exception never propagates into
the agent run. Requires ``autogen`` for real traffic; the proxy and the
event handler are testable against fakes without it.
"""

from __future__ import annotations

import logging
import types
from contextlib import contextmanager
from typing import Any, ClassVar, Optional

# event type names (suffix-matched) -> how to record them
_KNOWN = (
    "LLMCallEvent",
    "LLMStreamEndEvent",
    "FunctionCallEvent",
    "FunctionExecutionEvent",
    "SelectSpeakerEvent",
    "TerminationEvent",
)


def _preview(value: Any, limit: int = 200) -> str:
    if value is None:
        return ""
    text = str(value)
    return " ".join(text.split())[:limit]


def _field(obj: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        value = getattr(obj, name, None)
        if value is not None:
            return value
    return default


def _known_type(obj: Any) -> Optional[str]:
    if obj is None or isinstance(obj, str):
        return None
    name = type(obj).__name__
    return name if name in _KNOWN else None


class AutoGenEventHandler(logging.Handler):
    """Converts ``autogen_core.events`` objects into recorder steps."""

    def __init__(self, recorder):
        super().__init__(level=logging.INFO)
        self.recorder = recorder
        self.recorded = 0

    def emit(self, record: logging.LogRecord) -> None:
        try:
            event = record.msg
            kind = _known_type(event)
            if kind is None:
                return
            self._record(kind, event)
            self.recorded += 1
        except Exception:  # never break the agent run
            pass

    def _record(self, kind: str, event: Any) -> None:
        handler = self._HANDLERS.get(kind)
        if handler is not None:
            handler(self, event)

    def _agent(self, event: Any) -> str:
        return _preview(_field(event, "agent_id", "agent"), limit=80)

    def _llm_call(self, event: Any) -> None:
        self.recorder.tool(
            "llm",
            {"agent": self._agent(event)},
            result=_preview(_field(event, "response")),
            tokens=_field(event, "completion_tokens", default=0) or 0,
        )

    def _llm_stream_end(self, event: Any) -> None:
        self.recorder.tool(
            "llm-stream",
            {"agent": self._agent(event)},
            result=_preview(_field(event, "response")),
        )

    def _function_call(self, event: Any) -> None:
        name = _preview(_field(event, "function", "name"), limit=80) \
            or "function"
        self.recorder.tool(name, {"agent": self._agent(event)},
                           result=_preview(_field(event, "content", "args")))

    def _function_execution(self, event: Any) -> None:
        fn = _preview(_field(event, "function", "name"), limit=80) or "tool"
        self.recorder.observe(
            f"result of {fn}: {_preview(_field(event, 'content'), limit=120)}"
        )

    def _select_speaker(self, event: Any) -> None:
        speakers = _field(event, "speakers", default=[]) or []
        names = ", ".join(_preview(s, limit=40) for s in speakers)
        self.recorder.observe(f"select speaker: {names}")

    def _termination(self, event: Any) -> None:
        self.recorder.observe(
            f"termination: {_preview(_field(event, 'content'))}", verify=True
        )

    _HANDLERS: ClassVar[dict] = {
        "LLMCallEvent": _llm_call,
        "LLMStreamEndEvent": _llm_stream_end,
        "FunctionCallEvent": _function_call,
        "FunctionExecutionEvent": _function_execution,
        "SelectSpeakerEvent": _select_speaker,
        "TerminationEvent": _termination,
    }


class RecordingChatCompletionClient:
    """Transparent proxy recording every ``create()`` at the model boundary.

    Delegates all attributes to the wrapped client; only ``create`` is
    intercepted. ``create_stream`` passes through unrecorded (chunk
    generators cannot be consumed transparently) — pair with the event
    handler when you need streaming coverage.
    """

    def __init__(self, inner: Any, recorder=None, task: str = "autogen run"):
        from ..recorder import Recorder

        self._inner = inner
        self.recorder = recorder or Recorder(task, model="autogen",
                                             save=False)
        self._final: Optional[str] = None

    def create(self, messages: Any = None, **kwargs: Any) -> Any:
        result = self._inner.create(messages, **kwargs)
        try:
            self._record_create(result)
        except Exception:  # recording must not break inference
            pass
        return result

    def _record_create(self, result: Any) -> None:
        content = getattr(result, "content", None)
        usage = getattr(result, "usage", None)
        tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        model = type(self._inner).__name__
        info = getattr(self._inner, "model_info", None)
        family = info.get("family") if isinstance(info, dict) else None
        finish = _preview(getattr(result, "finish_reason", None), limit=40)
        self.recorder.tool(
            "llm",
            {"model": family or model, "finish_reason": finish},
            result=_preview(content),
            tokens=tokens,
        )
        self._final = _preview(content, limit=400) or self._final

    def create_stream(self, *args: Any, **kwargs: Any) -> Any:
        return self._inner.create_stream(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    # -- convenience -----------------------------------------------------------
    def respond(self, text: Optional[str] = None,
                success: bool = True) -> None:
        self.recorder.respond(text or self._final or "run finished",
                              success=success)

    def report(self):
        from ..attributor import attribute

        return attribute(self.recorder.trace)


@contextmanager
def record_autogen(task: str, *,
                   logger_name: str = "autogen_core.events",
                   level: int = logging.INFO):
    """Attach an :class:`AutoGenEventHandler` for the duration of a run."""
    from ..recorder import Recorder

    rec = Recorder(task, model="autogen", save=False)
    handler = AutoGenEventHandler(rec)
    handler.setLevel(level)
    logger = logging.getLogger(logger_name)
    logger.addHandler(handler)
    try:
        yield types.SimpleNamespace(
            recorder=rec,
            handler=handler,
            trace=lambda: rec.trace,
        )
    finally:
        logger.removeHandler(handler)
