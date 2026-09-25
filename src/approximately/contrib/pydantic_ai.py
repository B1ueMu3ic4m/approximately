"""Pydantic AI adapter (post-hoc message transcription).

Pydantic AI hands you the full message history when a run finishes
(``result.all_messages()``); this adapter turns that history into an
approximately trace — no hooks, no imports from the framework, works
with any object that quacks like a pydantic-ai message::

    from approximately.contrib.pydantic_ai import (
        record_pydantic_result, trace_from_pydantic_ai,
    )

    result = agent.run_sync("book the flight")        # pydantic-ai run
    trace = record_pydantic_result("book the flight", result,
                                   store=TraceStore("traces"))
    report = attribute(trace)                          # standard postmortem

Part mapping: ``UserPromptPart`` -> plan step, ``ToolCallPart`` ->
tool_call step (name + args), ``ToolReturnPart`` -> observe step with
the returned content, ``TextPart`` -> response step. Token usage is
read from each response's ``usage()`` (both the ``input_tokens``/
``output_tokens`` and the older ``request_tokens``/``response_tokens``
naming). Anything unrecognized is skipped, never fatal.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Optional

from ..store import TraceStore
from ..trace import Trace


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


def _usage_tokens(usage: Any) -> Optional[int]:
    """Total tokens from a pydantic-ai Usage, either naming era."""
    if usage is None:
        return None
    for pair in (("input_tokens", "output_tokens"),
                 ("request_tokens", "response_tokens")):
        a = getattr(usage, pair[0], None)
        b = getattr(usage, pair[1], None)
        if a is not None or b is not None:
            return int(a or 0) + int(b or 0)
    total = getattr(usage, "total_tokens", None)
    return int(total) if total is not None else None


def _current_message(state: dict) -> Any:
    return state.get("message")


def _response_usage(message: Any) -> Any:
    usage = getattr(message, "usage", None)
    if callable(usage):
        try:
            return usage()
        except Exception:
            return None
    return usage


def _transcribe_part(rec, part: Any, state: dict) -> None:
    """Record one pydantic-ai part into the recorder."""
    pkind = type(part).__name__
    if pkind in ("UserPromptPart", "SystemPromptPart"):
        rec.plan(_preview(getattr(part, "content", None)))
    elif pkind == "ToolCallPart":
        args = getattr(part, "args", None)
        rec.tool(str(getattr(part, "tool_name", "tool")),
                 args if isinstance(args, dict)
                 else {"args": _preview(args)})
    elif pkind == "ToolReturnPart":
        tokens = _usage_tokens(_response_usage(_current_message(state)))
        step = rec.tool(
            str(getattr(part, "tool_name", "tool")),
            {},
            result=_preview(getattr(part, "content", None)),
        )
        if tokens is not None:
            step.tokens = tokens
    elif pkind == "TextPart" or pkind == "ThinkingPart":
        text = _preview(getattr(part, "content", None))
        if pkind == "TextPart":
            state["final_output"] = text
            rec.respond(text)
        else:
            rec.plan(text)
    elif pkind == "RetryPromptPart":
        rec.tool("retry", {},
                 result=_preview(getattr(part, "content", None)),
                 error="validation retry")
    # unknown part types are skipped by design


def trace_from_pydantic_ai(messages: Iterable[Any],
                           task: str = "pydantic-ai run",
                           model: str = "pydantic-ai") -> Trace:
    """Transcribe a pydantic-ai message history into a Trace."""
    from ..recorder import Recorder

    rec = Recorder(task, model=model, save=False)
    state: dict = {"message": None, "final_output": ""}
    for message in messages:
        state["message"] = message
        parts = getattr(message, "parts", None) or []
        if not parts and isinstance(getattr(message, "content", None), str):
            # bare request/response objects without part wrappers
            text = _preview(message.content)
            if "Response" in type(message).__name__:
                rec.respond(text)
            else:
                rec.plan(text)
            continue
        for part in parts:
            _transcribe_part(rec, part, state)
    trace = rec.trace
    final_output = state["final_output"]
    if final_output:
        trace.success = True
        trace.final_output = final_output
    return trace


def record_pydantic_result(task: str, result: Any,
                           store: Optional[TraceStore] = None,
                           model: str = "pydantic-ai") -> Trace:
    """Transcribe a finished pydantic-ai run result and save it.

    ``result`` is anything exposing ``all_messages()`` (a pydantic-ai
    ``AgentRunResult``). The run's final output becomes the response;
    success is recorded as ``True`` — a crashed run never reaches
    ``all_messages()``, and the failure detectors judge what's here.
    """
    messages = result.all_messages()
    trace = trace_from_pydantic_ai(messages, task=task, model=model)
    output = getattr(result, "output", None)
    if output is not None:
        trace.final_output = _preview(output)
    if trace.steps and trace.success is None:
        trace.success = True
    if store is not None:
        store.save(trace)
    return trace
