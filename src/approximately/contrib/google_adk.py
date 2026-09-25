"""Google ADK adapter (post-hoc event transcription).

A google-adk run is a list of ``Event`` objects (``Runner.run`` /
``runner.run`` yields them, or ``session.events`` after the fact);
this adapter turns that history into an approximately trace — no
imports from the framework, works with any object that quacks like
an ADK event::

    from approximately.contrib.google_adk import (
        record_adk_events, trace_from_adk_events,
    )

    events = list(runner.run(session, content))       # google-adk run
    trace = trace_from_adk_events(events, task="book the flight")
    report = attribute(trace)                          # standard postmortem

Event mapping (each event carries ``content.parts`` in the genai
shape): a part with ``function_call`` -> tool-call step (name +
args), ``function_response`` -> tool-result step (name + response
preview), ``text`` -> plan step from the user side / response step
from the agent side (the last agent text becomes ``final_output``).
``usage_metadata``'s ``prompt_token_count``/``candidates_token_count``
are summed into the step's tokens when present. Events without
content, parts, or recognized shapes are skipped, never fatal.
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
    prompt = getattr(usage, "prompt_token_count", None) if usage else None
    candidates = (getattr(usage, "candidates_token_count", None)
                  if usage else None)
    if prompt is None and candidates is None:
        return None
    return int(prompt or 0) + int(candidates or 0)


def _event_usage(event: Any) -> Any:
    return getattr(event, "usage_metadata", None)


def _transcribe_part(rec, part: Any, state: dict, agent_side: bool) -> None:
    call = getattr(part, "function_call", None)
    response = getattr(part, "function_response", None)
    text = getattr(part, "text", None)
    if call is not None:
        args = getattr(call, "args", None)
        rec.tool(str(getattr(call, "name", "tool")),
                 args if isinstance(args, dict)
                 else {"args": _preview(args)})
    elif response is not None:
        tokens = _usage_tokens(_event_usage(state.get("event")))
        step = rec.tool(str(getattr(response, "name", "tool")), {},
                        result=_preview(getattr(response, "response",
                                                None)))
        if tokens is not None:
            step.tokens = tokens
    elif isinstance(text, str) and text.strip():
        if agent_side:
            state["final_output"] = text
            rec.respond(text)
        else:
            rec.plan(text)
    # parts with neither call, response, nor text are skipped by design


def trace_from_adk_events(events: Iterable[Any],
                          task: str = "google-adk run",
                          model: str = "google-adk") -> Trace:
    """Transcribe a google-adk event list into a Trace."""
    from ..recorder import Recorder

    rec = Recorder(task, model=model, save=False)
    state: dict = {"event": None, "final_output": ""}
    for event in events:
        state["event"] = event
        content = getattr(event, "content", None)
        parts = getattr(content, "parts", None) or []
        if not parts:
            continue  # control events (yield, transfer, auth) carry no text
        agent_side = getattr(event, "author", "user") != "user"
        for part in parts:
            _transcribe_part(rec, part, state, agent_side)
    trace = rec.trace
    final_output = state["final_output"]
    if final_output:
        trace.success = True
        trace.final_output = final_output
    return trace


def record_adk_events(task: str, events: Iterable[Any],
                      store: Optional[TraceStore] = None,
                      model: str = "google-adk") -> Trace:
    """Transcribe a finished google-adk run and optionally save it."""
    trace = trace_from_adk_events(events, task=task, model=model)
    if trace.steps and trace.success is None:
        trace.success = True
    if store is not None:
        store.save(trace)
    return trace
