"""LangChain / LangGraph adapter.

Drop one handler into your LangGraph or LangChain ``config["callbacks"]``
and every tool call, model error, and chain-level failure lands in an
approximately trace::

    from approximately.contrib.langgraph import ApproximatelyCallbackHandler

    handler = ApproximatelyCallbackHandler("book a flight")
    graph.invoke(inputs, config={"callbacks": [handler]})
    report = attribute(handler.recorder.trace)   # postmortem for free

Requires ``langchain-core`` (already present in any LangGraph install).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..attributor import FailureReport

import json
from typing import Any, Dict, Optional

from ..recorder import Recorder

try:
    from langchain_core.callbacks import BaseCallbackHandler as _LCBaseHandler
except ImportError:  # core stays dependency-free; adapter needs it at import
    class _LCBaseHandler:  # type: ignore[no-redef]  # pragma: no cover
        pass


def _dig(obj: Any, *path: str) -> Any:
    """Walk dicts/objects along a path; None the moment a link is
    missing (framework response shapes drift)."""
    for key in path:
        if obj is None:
            return None
        obj = (obj.get(key) if isinstance(obj, dict)
               else getattr(obj, key, None))
    return obj


def _usage_tokens(response: Any) -> int:
    """Total tokens from a LangChain LLM result, any naming era:
    llm_output.token_usage, per-generation response_metadata /
    usage_metadata, or a top-level usage_metadata."""
    top_paths: tuple[tuple[str, ...], ...] = (
        ("llm_output", "token_usage", "total_tokens"),
        ("usage_metadata", "total_tokens"))
    for path in top_paths:
        value = _dig(response, *path)
        if isinstance(value, (int, float)):
            return int(value)
    generations = getattr(response, "generations", None) or []
    paths: tuple[tuple[str, ...], ...] = (
        ("message", "response_metadata",
         "token_usage", "total_tokens"),
        ("message", "usage_metadata", "total_tokens"),
        ("usage_metadata", "total_tokens"),
        ("generation_info", "token_usage", "total_tokens"))
    for batch in generations:
        for gen in batch:
            for path in paths:
                value = _dig(gen, *path)
                if isinstance(value, (int, float)):
                    return int(value)
    return 0


def _response_text(response: Any) -> str:
    generations = getattr(response, "generations", None) or []
    for batch in generations:
        for gen in batch:
            text = getattr(gen, "text", None)
            if text:
                return _preview(text)
            content = _dig(gen, "message", "content")
            if content:
                return _preview(content)
    return ""


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


class ApproximatelyCallbackHandler(_LCBaseHandler):
    """LangChain callback handler that records into an approximately trace.

    Works with any callback-compatible runnable — LangGraph agents included,
    since LangGraph drives the same callback manager.
    """

    def __init__(self, task: str, model: str = "langchain", recorder: Optional[Recorder] = None):
        self.recorder = recorder or Recorder(task, model=model, save=False)
        self._tool_by_run: Dict[Any, str] = {}
        self._chain_depth = 0

    # -- LangChain protocol ---------------------------------------------------
    raise_error: bool = False  # never break the user's run over recording issues

    def on_chain_start(self, serialized: Optional[Dict], inputs: Dict[str, Any],
                       *, run_id: Any = None, **kwargs: Any) -> None:
        self._chain_depth += 1

    def on_chain_end(self, outputs: Optional[Dict[str, Any]],
                     *, run_id: Any = None, **kwargs: Any) -> None:
        self._chain_depth = max(0, self._chain_depth - 1)

    def on_chain_error(self, error: BaseException, *, run_id: Any = None,
                       **kwargs: Any) -> None:
        self.recorder.fail(f"{type(error).__name__}: {error}")

    def on_tool_start(self, serialized: Optional[Dict[str, Any]],
                      input_str: str, *, run_id: Any = None, **kwargs: Any) -> None:
        name = (serialized or {}).get("name") or "unknown_tool"
        self._tool_by_run[run_id] = name
        # the actual Step is written at on_tool_end/on_tool_error when we
        # know the outcome; nothing to do here beyond remembering the name

    def on_tool_end(self, output: Any, *, run_id: Any = None,
                    **kwargs: Any) -> None:
        name = self._tool_by_run.pop(run_id, "unknown_tool")
        self.recorder.tool(name, {}, result=_preview(output))

    def on_tool_error(self, error: BaseException, *, run_id: Any = None,
                      **kwargs: Any) -> None:
        name = self._tool_by_run.pop(run_id, "unknown_tool")
        self.recorder.tool(name, {}, error=f"{type(error).__name__}: {error}")

    def on_chat_model_start(self, serialized: Optional[Dict],
                            messages: Any, *, run_id: Any = None,
                            **kwargs: Any) -> None:
        self.recorder.plan(_preview(messages, 160))

    def on_llm_start(self, serialized: Optional[Dict[str, Any]],
                     prompts: Any, *, run_id: Any = None,
                     **kwargs: Any) -> None:
        # completion-style models: same treatment as chat models
        self.recorder.plan(_preview(prompts, 160))

    def on_llm_error(self, error: BaseException, *, run_id: Any = None,
                     **kwargs: Any) -> None:
        self.recorder.tool("llm", {}, error=f"{type(error).__name__}: {error}")

    def on_llm_end(self, response: Any, *, run_id: Any = None,
                   **kwargs: Any) -> None:
        # the completion and its usage land here — without this the
        # model's answer (and the token receipt) never reaches the
        # trace, and the token-baseline family starves
        self.recorder.tool("llm", {}, result=_response_text(response),
                           tokens=_usage_tokens(response))

    def on_chat_model_end(self, response: Any, *, run_id: Any = None,
                          **kwargs: Any) -> None:
        self.on_llm_end(response, run_id=run_id, **kwargs)

    # -- convenience -----------------------------------------------------------
    def respond(self, text: str, success: bool = True) -> None:
        self.recorder.respond(text, success=success)

    def report(self) -> "FailureReport":
        """Attribute the recorded trace (rules by default)."""
        from ..attributor import attribute

        return attribute(self.recorder.trace)
