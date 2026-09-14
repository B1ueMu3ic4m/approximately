"""OpenAI Agents SDK adapter.

Add one processor and every Agents SDK run gets a postmortem::

    from approximately.contrib.agents_sdk import AgentsSDKProcessor

    processor = AgentsSDKProcessor("research task")
    add_trace_processor(processor)
    await Runner.run(agent, "do the thing")
    report = attribute(processor.recorder.trace)

Requires ``openai-agents``.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar, Optional


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
    text = " ".join(text.split())
    return text[:limit]


class AgentsSDKProcessor:
    """TracingProcessor that records function/generation spans into a trace."""

    def __init__(self, task: str, recorder=None):
        from ..recorder import Recorder

        self.recorder = recorder or Recorder(task, model="openai-agents",
                                             save=False)
        self.task = task          # fallback when traces carry no name
        self._final_output: Optional[str] = None

    # -- TracingProcessor protocol ---------------------------------------------
    def on_trace_start(self, trace: Any) -> None:
        # the SDK's trace name is the real task; constructor value is fallback
        if trace and getattr(trace, "name", None) and \
                self.recorder.trace.task == self.task:
            self.recorder.trace.task = trace.name

    def on_trace_end(self, trace: Any) -> None:
        pass  # response/agent spans carry the outcome already

    def on_span_start(self, span: Any) -> None:
        pass  # record on end, when output and error are both known

    def on_span_end(self, span: Any) -> None:
        data = getattr(span, "span_data", None)
        if data is None:
            return
        handler = self._SPAN_HANDLERS.get(type(data).__name__)
        if handler is not None:
            handler(self, data, getattr(span, "error", None))

    def _on_function(self, data: Any, error: Any) -> None:
        args = {}
        try:
            parsed = json.loads(data.input) if data.input else {}
            if isinstance(parsed, dict):
                args = parsed
        except (json.JSONDecodeError, TypeError):
            args = {"input": _preview(data.input)}
        self.recorder.tool(
            data.name or "function",
            args,
            result=_preview(data.output),
            error=error,
        )

    def _on_generation(self, data: Any, error: Any) -> None:
        usage = (getattr(data, "usage", None) or {})
        model = getattr(data, "model", None) or "llm"
        self.recorder.tool(
            "llm",
            {"model": model},
            result=_preview(getattr(data, "output", None)),
            error=error,
            tokens=usage.get("output_tokens", 0),
        )

    def _on_agent(self, data: Any, error: Any) -> None:
        self.recorder.observe(f"agent: {getattr(data, 'name', '?')}")

    def _on_handoff(self, data: Any, error: Any) -> None:
        self.recorder.observe(
            f"handoff {getattr(data, 'from_agent', '?')} -> "
            f"{getattr(data, 'to_agent', '?')}", verify=True
        )

    def _on_response(self, data: Any, error: Any) -> None:
        response = getattr(data, "response", None)
        text = _preview(getattr(response, "output_text", None) or response)
        self._final_output = text or self._final_output

    _SPAN_HANDLERS: ClassVar[dict] = {
        "FunctionSpanData": _on_function,
        "GenerationSpanData": _on_generation,
        "AgentSpanData": _on_agent,
        "HandoffSpanData": _on_handoff,
        "ResponseSpanData": _on_response,
    }

    # -- convenience -----------------------------------------------------------
    def respond(self, text: Optional[str] = None,
                success: bool = True) -> None:
        self.recorder.respond(text or self._final_output or "run finished",
                              success=success)

    def report(self):
        from ..attributor import attribute

        return attribute(self.recorder.trace)
