"""Export stored traces back out as foreign transcript JSONL.

`importer.py` is the path in; this is the path out.  The OpenAI chat
shape is the interchange dialect most tools agree on, so that is the
default export: fine-tuning pipelines, eval harnesses and other agent
stacks can consume a tamper-evident store without learning ours.
``native`` exports serialize the Trace verbatim (a lossless,
hash-chain-preserving roundtrip).  ``otel`` emits an OTLP JSON
``ExportTraceServiceRequest`` — one root span per run, one span per
step — which tracing backends (Jaeger, Tempo, Honeycomb) ingest
natively, so agent failures surface next to the rest of the stack's
telemetry.

The chat shape is lossy by design: success flags, hashes and timing
do not exist in the dialect.  Tool errors are preserved the way the
API spells them (``is_error: true`` on the tool message), which is
exactly what :mod:`approximately.importer` reads back.  The OTLP
shape reconstructs the per-step timeline from ``latency_ms`` (the
recorder keeps no per-step wall clock) and says so via the
``approximately.time.derived`` attribute on every span.
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List, Optional

from .store import TraceStore
from .trace import MESSAGE, OBSERVATION, PLAN, RESPONSE, TOOL_CALL, Trace

OPENAI_JSONL = "openai-jsonl"
NATIVE = "native"
OTEL = "otel"
_FORMATS = (OPENAI_JSONL, NATIVE, OTEL)

# OTLP JSON per the spec: 64-bit integers (nanosecond timestamps,
# int attribute values) as decimal strings, ids as hex.  Consumers
# (Jaeger, Tempo, Honeycomb) ingest this shape directly.
_TEXT_CAP = 8192
_TASK_SPAN_CAP = 120


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


# ---------------------------------------------------------------- OTLP


def _cap(text: Any) -> str:
    return str(text)[:_TEXT_CAP]


def _attr(key: str, value: Any) -> Optional[Dict[str, Any]]:
    """One OTLP attribute; None for values the dialect cannot carry
    (None itself)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    if isinstance(value, float):
        return {"key": key, "value": {"doubleValue": value}}
    return {"key": key, "value": {"stringValue": _cap(value)}}


def _attrs(pairs) -> List[Dict[str, Any]]:
    out = [a for a in (_attr(k, v) for k, v in pairs) if a is not None]
    # key order for byte-stable output regardless of dict ordering
    return sorted(out, key=lambda a: a["key"])


def _span(trace_id: str, index: int) -> str:
    return sha256(f"{trace_id}:{index}".encode()).hexdigest()[:16]


def _trace_id(trace_id: str) -> str:
    return sha256(f"trace:{trace_id}".encode()).hexdigest()[:32]


def _nanos(t: float) -> str:
    return str(int(t * 1_000_000_000))


_STATUS_OK = 1
_STATUS_ERROR = 2


def trace_to_spans(trace: Trace) -> List[Dict[str, Any]]:
    """One trace as OTLP spans: a root span for the run, one child per
    recorded step.  Deterministic — the same trace always yields the
    same span ids, timestamps and attribute bytes."""
    root_id = _trace_id(trace.id)
    base = trace.created_at if trace.created_at > 0 else 0.0
    cursor = base
    spans: List[Dict[str, Any]] = []
    for step in trace.steps:
        dur_ms = step.latency_ms if step.latency_ms > 0 else 0
        start = cursor
        cursor = start + dur_ms / 1000.0
        attrs = _attrs([
            ("approximately.kind", step.kind),
            ("approximately.tool", step.tool),
            ("approximately.agent", step.agent),
            ("approximately.error", step.error),
            ("approximately.tokens", step.tokens or None),
            ("approximately.latency_ms", step.latency_ms or None),
            ("approximately.step", step.index),
            ("approximately.args", json.dumps(step.args or {},
                                              default=str) or None),
            ("approximately.result", step.result or None),
            ("approximately.thought", step.thought or None),
            ("approximately.time.derived", True),
        ])
        spans.append({
            "traceId": root_id,
            "spanId": _span(trace.id, step.index),
            "parentSpanId": _span(trace.id, -1),
            "name": _cap(step.tool or step.kind),
            "kind": 1,
            "startTimeUnixNano": _nanos(start),
            "endTimeUnixNano": _nanos(max(start, cursor)),
            "attributes": attrs,
            **({"status": {"code": _STATUS_ERROR}}
               if step.error else {}),
        })
    task = " ".join(str(trace.task).split())
    root: Dict[str, Any] = {
        "traceId": root_id,
        "spanId": _span(trace.id, -1),
        "parentSpanId": "",
        "name": _cap(task)[:_TASK_SPAN_CAP] or "agent run",
        "kind": 1,
        "startTimeUnixNano": _nanos(base),
        "endTimeUnixNano": _nanos(max(base, cursor)),
        "attributes": _attrs([
            ("approximately.trace.id", trace.id),
            ("approximately.task", trace.task),
            ("approximately.model", trace.model),
            ("approximately.final_output", trace.final_output),
            ("approximately.step.count", len(trace.steps)),
            ("approximately.time.derived", True),
            *((f"approximately.meta.{k}", v)
              for k, v in sorted((trace.meta or {}).items())
              if isinstance(v, (str, int, float, bool))),
        ]),
        "status": ({"code": _STATUS_ERROR}
                   if trace.success is False
                   else {"code": _STATUS_OK} if trace.success else
                   {"code": 0}),
    }
    return [root, *spans]


def export_otlp(traces: List[Trace]) -> Dict[str, Any]:
    """All traces as one OTLP ``ExportTraceServiceRequest`` document."""
    resource = {"attributes": _attrs([
        ("service.name", "approximately"),
        ("approximately.version", _dist_version()),
    ])}
    spans: List[Dict[str, Any]] = []
    for trace in sorted(traces, key=lambda t: t.id):
        spans.extend(trace_to_spans(trace))
    return {"resourceSpans": [{
        "resource": resource,
        "scopeSpans": [{
            "scope": {"name": "approximately.exporter"},
            "spans": spans,
        }],
    }]}


def _dist_version() -> str:
    try:
        from importlib import metadata

        return metadata.version("approximately")
    except Exception:
        return "unknown"


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
                 since_days: Optional[int] = None,
                 dedupe: bool = False) -> Dict[str, Any]:
    """Write every trace (or the query/age-selected subset) to
    ``output`` as JSONL; returns the counts written. ``dedupe``
    drops near-duplicate traces (alignment clustering) so a shared
    export carries one copy of each run."""
    if fmt not in _FORMATS:
        raise ValueError(f"unknown format {fmt!r}; expected one of "
                         f"{', '.join(_FORMATS)}")
    traces = store.list_traces(since_days=since_days)
    if query_text:
        from .query import select

        traces = select(traces, query_text)
    dropped = 0
    if dedupe:
        from .align import dedupe_traces

        traces, dropped = dedupe_traces(traces)
    # id order, not mtime order: filesystems time-stamp with different
    # granularity (Windows ties break by glob order), and the same
    # content must export to identical bytes everywhere
    traces = sorted(traces, key=lambda t: t.id)
    written = 0
    if fmt == OTEL:
        with output.open("w", encoding="utf-8") as fh:
            json.dump(export_otlp(traces), fh, ensure_ascii=False)
            fh.write("\n")
        return {"format": fmt, "traces": len(traces),
                "written": len(traces), "dedupe_dropped": dropped,
                "output": str(output)}
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
            "dedupe_dropped": dropped, "output": str(output)}
