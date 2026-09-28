"""Export stored traces back out as foreign transcript JSONL.

`importer.py` is the path in; this is the path out.  The OpenAI chat
shape is the interchange dialect most tools agree on, so that is the
default export: fine-tuning pipelines, eval harnesses and other agent
stacks can consume a tamper-evident store without learning ours.
``native`` exports serialize the Trace verbatim (a lossless,
hash-chain-preserving roundtrip).

The chat shape is lossy by design: success flags, hashes and timing
do not exist in the dialect.  Tool errors are preserved the way the
API spells them (``is_error: true`` on the tool message), which is
exactly what :mod:`approximately.importer` reads back.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .store import TraceStore
from .trace import MESSAGE, OBSERVATION, PLAN, RESPONSE, TOOL_CALL, Trace

OPENAI_JSONL = "openai-jsonl"
NATIVE = "native"
_FORMATS = (OPENAI_JSONL, NATIVE)


def _content(text: str) -> Any:
    return text if text else ""


def _tool_result(name, call_id, text, error) -> Dict[str, Any]:
    msg: Dict[str, Any] = {"role": "tool",
                           "name": name or "tool",
                           "content": _content(text)}
    if call_id:
        msg["tool_call_id"] = call_id
    if error:
        msg["is_error"] = True
    return msg


def _simple_message(step) -> Dict[str, Any]:
    if step.kind == OBSERVATION:
        return _tool_result(step.tool, None, step.result, step.error)
    if step.kind == RESPONSE:
        return {"role": "assistant", "content": _content(step.result)}
    if step.kind == PLAN:
        return {"role": "assistant",
                "content": _content(step.thought or "")}
    if step.kind == MESSAGE:
        return {"role": str(step.meta.get("role", "user")),
                "content": _content(step.result)}
    return {"role": "assistant",          # ERROR
            "content": _content(step.error or ""),
            "is_error": True}


def _emit_call_block(steps, i, total, messages, call_no):
    """Emit one run of adjacent tool_call steps as a single assistant
    message plus its tool results; returns (next index, next number)."""
    block = []
    while i < total and steps[i].kind == TOOL_CALL:
        block.append(steps[i])
        i += 1
    messages.append({"role": "assistant", "content": None,
                     "tool_calls": []})
    ids = []
    for call in block:
        call_id = f"call_{call_no}"
        call_no += 1
        ids.append(call_id)
        messages[-1]["tool_calls"].append({
            "type": "function",
            "function": {"name": call.tool or "unknown",
                         "arguments": json.dumps(call.args or {})},
            "id": call_id,
        })
    used = 0
    while (used < len(ids) and i < total
           and steps[i].kind == OBSERVATION):
        obs = steps[i]
        i += 1
        messages.append(_tool_result(obs.tool or block[used].tool,
                                     ids[used], obs.result, obs.error))
        used += 1
    for call, call_id in zip(block[used:], ids[used:]):
        messages.append(_tool_result(call.tool, call_id,
                                     call.error or call.result,
                                     call.error))
    return i, call_no


def _tool_messages(steps) -> List[Dict[str, Any]]:
    """Invert steps to chat-API messages.  A run of adjacent tool_call
    steps is one assistant message; the observations that follow pair
    with the call ids in order, and any call the observations don't
    cover emits its tool message from the result/error the recorder
    keeps on the call step itself."""
    messages: List[Dict[str, Any]] = []
    call_no = 0
    i = 0
    total = len(steps)
    while i < total:
        step = steps[i]
        if step.kind == TOOL_CALL:
            i, call_no = _emit_call_block(steps, i, total, messages,
                                          call_no)
            continue
        messages.append(_simple_message(step))
        i += 1
    return messages


def trace_to_messages(trace: Trace) -> List[Dict[str, Any]]:
    return _tool_messages(trace.steps)


def export_annotations(store: TraceStore, output: Path) -> int:
    """Write the annotation sidecar alongside a transcript export so
    a store handoff carries the triage story too. Returns the row
    count."""
    rows = store.annotations()
    with output.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(rows)


def export_store(store: TraceStore, output: Path,
                 fmt: str = OPENAI_JSONL,
                 query_text: Optional[str] = None,
                 since_days: Optional[int] = None) -> Dict[str, Any]:
    """Write every trace (or the query/age-selected subset) to
    ``output`` as JSONL; returns the counts written."""
    if fmt not in _FORMATS:
        raise ValueError(f"unknown format {fmt!r}; expected one of "
                         f"{', '.join(_FORMATS)}")
    traces = store.list_traces(since_days=since_days)
    if query_text:
        from .query import select

        traces = select(traces, query_text)
    # id order, not mtime order: filesystems time-stamp with different
    # granularity (Windows ties break by glob order), and the same
    # content must export to identical bytes everywhere
    traces = sorted(traces, key=lambda t: t.id)
    written = 0
    with output.open("w", encoding="utf-8") as fh:
        for trace in traces:
            row = (trace.to_dict() if fmt == NATIVE
                   else {"messages": _tool_messages(trace.steps),
                         "metadata": {"task": trace.task,
                                      "success": trace.success,
                                      "trace_id": trace.id}})
            fh.write(json.dumps(row, default=str) + "\n")
            written += 1
    return {"format": fmt, "traces": len(traces), "written": written,
            "output": str(output)}
