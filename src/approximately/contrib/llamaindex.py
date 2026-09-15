"""LlamaIndex adapter (best-effort, callback-handler seam).

LlamaIndex (v0.9 → current) fans every internal event out through a
:class:`~llama_index.core.callbacks.CallbackManager`; handlers receive
typed events (LLM, FUNCTION_CALL, AGENT_STEP, RETRIEVE, EXCEPTION, ...)
with a payload dict. Add one handler and every query/synthesis run gets
a postmortem::

    from approximately.contrib.llamaindex import ApproximatelyHandler

    handler = ApproximatelyHandler("quarterly numbers")
    index.query("revenue", callback_manager=CallbackManager([handler]))
    # or globally:
    Settings.callback_manager = CallbackManager([handler])
    report = attribute(handler.recorder.trace)

The handler is duck-typed (no ``llama_index`` import needed to define
it) and version-tolerant: event types arrive as ``CBEventType`` enums or
plain strings depending on the release, payload keys are looked up by
their documented string values with defensive fallbacks, and any
extraction failure is swallowed rather than breaking your query.
"""

from __future__ import annotations

import json
from typing import Any, Optional

# LlamaIndex EventPayload members are str-valued; use the literal values
# so the adapter needs no llama_index import.
_PROMPT, _COMPLETION, _RESPONSE = "prompt", "completion", "response"
_FUNCTION_CALL, _FUNCTION_OUTPUT = "function_call", "function_output"
_EXCEPTION = "exception"


def _preview(value: Any, limit: int = 200) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, default=str)
        except Exception:
            text = str(value)
    return " ".join(text.split())[:limit]


def _event_name(event_type: Any) -> str:
    """CBEventType enum across versions, or a plain string."""
    if isinstance(event_type, str):
        return event_type.upper()
    name = getattr(event_type, "name", None)
    return str(name or event_type).upper()


class ApproximatelyHandler:
    """Duck-typed LlamaIndex callback handler recording into a trace.

    Satisfies the ``BaseCallbackHandler`` protocol (``on_event_start``,
    ``on_event_end``, ``start_trace``, ``end_trace``) without importing
    it — LlamaIndex calls the methods, it does not type-check them.
    """

    def __init__(self, task: str, recorder=None):
        from ..recorder import Recorder

        self.recorder = recorder or Recorder(task, model="llamaindex",
                                             save=False)
        self.task = task
        self._last_function: Optional[str] = None

    # -- CallbackHandler protocol ---------------------------------------------
    def on_event_start(self, event_type: Any, payload: Optional[dict] = None,
                       event_id: str = "", parent_id: str = "",
                       **kwargs: Any) -> None:
        pass  # record on end, when the outcome is known

    def on_event_end(self, event_type: Any, payload: Optional[dict] = None,
                     event_id: str = "", parent_id: str = "",
                     **kwargs: Any) -> None:
        try:
            self._on_end(_event_name(event_type), payload or {})
        except Exception:  # never break the query
            pass

    def start_trace(self, trace_id: str, **kwargs: Any) -> None:
        pass

    def end_trace(self, trace_id: str, trace_map: Optional[dict] = None,
                  **kwargs: Any) -> None:
        pass

    # -- event mapping ----------------------------------------------------------
    def _on_end(self, name: str, payload: dict) -> None:
        handler = self._EVENTS.get(name)
        if handler is not None:
            handler(self, payload)

    def _llm(self, payload: dict) -> None:
        result = _preview(payload.get(_RESPONSE) or payload.get(_COMPLETION))
        prompt = _preview(payload.get(_PROMPT), limit=120)
        self.recorder.tool(
            "llm", {"prompt": prompt} if prompt else {},
            result=result,
        )

    def _function_call(self, payload: dict) -> None:
        raw = _preview(payload.get(_FUNCTION_CALL), limit=400)
        name, args = self._parse_call(raw)
        self._last_function = name
        self.recorder.tool(name, args,
                           result=_preview(payload.get(_FUNCTION_OUTPUT)))

    def _parse_call(self, raw: str) -> tuple:
        """LlamaIndex serialises calls as ``name <kwargs>`` where the
        kwargs are a dict repr in braces/parens or a free-form string."""
        raw = (raw or "").strip()
        if not raw or " " not in raw:
            return raw or "function", {}
        name, _, rest = raw.partition(" ")
        rest = rest.strip().strip("()").strip()
        try:
            parsed = json.loads(rest.replace("'", '"'))
            if isinstance(parsed, dict):
                return name, parsed
        except (json.JSONDecodeError, ValueError):
            pass
        return name, {"input": rest} if rest else {}

    def _agent_step(self, payload: dict) -> None:
        thought = _preview(payload.get(_PROMPT) or payload.get(_RESPONSE))
        self.recorder.observe(f"agent step: {thought}")

    def _retrieve(self, payload: dict) -> None:
        nodes = payload.get("nodes")
        count = len(nodes) if isinstance(nodes, (list, tuple)) else None
        detail = f"{count} nodes" if count is not None else "retrieved"
        self.recorder.tool("retrieve", {}, result=detail)

    def _exception(self, payload: dict) -> None:
        exc = payload.get(_EXCEPTION)
        self.recorder.fail(_preview(exc) or "exception event")

    # dispatch table: CBEventType name -> recorder action
    _EVENTS = {
        "LLM": _llm,
        "FUNCTION_CALL": _function_call,
        "AGENT_STEP": _agent_step,
        "RETRIEVE": _retrieve,
        "EXCEPTION": _exception,
    }

    # -- wiring & convenience ---------------------------------------------------
    def wire(self, manager_or_settings: Any):
        """Attach to a CallbackManager, or set one up on Settings-like."""
        add = getattr(manager_or_settings, "add_handler", None)
        if add is not None:  # a CallbackManager (or Dispatcher)
            add(self)
            return manager_or_settings
        try:
            from llama_index.core.callbacks import CallbackManager
        except ImportError as exc:
            raise RuntimeError(
                "wire() needs llama_index installed, or pass a "
                "CallbackManager directly") from exc
        manager = CallbackManager([self])
        manager_or_settings.callback_manager = manager
        return manager

    def respond(self, text: Optional[str] = None,
                success: bool = True) -> None:
        self.recorder.respond(text or "query finished", success=success)

    def report(self):
        from ..attributor import attribute

        return attribute(self.recorder.trace)


# friendly alias
LlamaIndexCallbackHandler = ApproximatelyHandler
