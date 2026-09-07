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

import json
from typing import Any, Dict, Optional

from ..recorder import Recorder

try:
    from langchain_core.callbacks import BaseCallbackHandler as _LCBaseHandler
except ImportError:  # core stays dependency-free; adapter needs it at import
    class _LCBaseHandler:  # pragma: no cover - only hit without langchain
        pass


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
    @property
    def raise_error(self) -> bool:
        return False  # never break the user's run over recording issues

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

    # -- convenience -----------------------------------------------------------
    def respond(self, text: str, success: bool = True) -> None:
        self.recorder.respond(text, success=success)

    def report(self):
        """Attribute the recorded trace (rules by default)."""
        from ..attributor import attribute

        return attribute(self.recorder.trace)
