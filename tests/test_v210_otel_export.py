"""v210: `export --format otel` — traces as OTLP spans.

Tracing backends (Jaeger, Tempo, Honeycomb) already hold the rest of
the stack's telemetry; this hands them the agent's part.  One root
span per run, one span per step, deterministic ids and bytes: the
same store always exports the same document, everywhere.
"""

import argparse
import itertools
import json

from approximately.cli import cmd_export
from approximately.exporter import _TEXT_CAP, OTEL, export_store, trace_to_spans
from approximately.mcp_server import ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore
from approximately.trace import Step, Trace


def _seed(directory, **kw):
    store = TraceStore(directory)
    trace = Trace(task="fix the login bug", id="abc123",
                  created_at=100.0, model="gpt-x", success=False,
                  final_output="gave up", meta={"env": "ci"}, **kw)
    trace.add(Step(kind="tool_call", tool="shell",
                   args={"cmd": "pytest"}, latency_ms=1200,
                   tokens=42, agent="worker"))
    trace.add(Step(kind="observation", tool="shell", result="3 failed",
                   error="exit 1", latency_ms=5))
    trace.add(Step(kind="response", result="cannot fix",
                   latency_ms=300))
    store.save(trace)
    return store


def _spans_of(envelope):
    return envelope["resourceSpans"][0]["scopeSpans"][0]["spans"]


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_envelope_structure(tmp_path):
    store = _seed(tmp_path / "s")
    out = tmp_path / "out.json"
    result = export_store(store, out, fmt=OTEL)
    assert result["written"] == 1
    env = _load(out)
    rs = env["resourceSpans"]
    assert len(rs) == 1
    resource = {a["key"]: a["value"] for a in
                rs[0]["resource"]["attributes"]}
    assert resource["service.name"]["stringValue"] == "approximately"
    scope = rs[0]["scopeSpans"][0]["scope"]
    assert scope["name"] == "approximately.exporter"


def test_root_span_shape_and_status(tmp_path):
    trace = Trace(task="  fix   the bug  ", id="abc123",
                  created_at=100.0, success=False)
    trace.add(Step(kind="plan", thought="try", latency_ms=10))
    root = trace_to_spans(trace)[0]
    assert len(root["traceId"]) == 32
    assert len(root["spanId"]) == 16
    assert root["parentSpanId"] == ""
    assert root["name"] == "fix the bug"
    assert root["status"] == {"code": 2}
    ok = trace_to_spans(Trace(task="t", success=True))[0]
    assert ok["status"] == {"code": 1}
    unknown = trace_to_spans(Trace(task="t", success=None))[0]
    assert unknown["status"] == {"code": 0}


def test_child_chain_and_error_status(tmp_path):
    store = _seed(tmp_path / "s")
    out = tmp_path / "out.json"
    export_store(store, out, fmt=OTEL)
    spans = _spans_of(_load(out))
    assert len(spans) == 4
    root = spans[0]
    for child in spans[1:]:
        assert child["traceId"] == root["traceId"]
        assert child["parentSpanId"] == root["spanId"]
    tool_span = spans[1]
    attrs = {a["key"]: a["value"] for a in tool_span["attributes"]}
    assert tool_span["name"] == "shell"
    assert attrs["approximately.tool"]["stringValue"] == "shell"
    assert attrs["approximately.agent"]["stringValue"] == "worker"
    assert attrs["approximately.tokens"]["intValue"] == "42"
    obs = spans[2]
    assert obs["status"] == {"code": 2}
    attrs = {a["key"]: a["value"] for a in obs["attributes"]}
    assert attrs["approximately.error"]["stringValue"] == "exit 1"


def test_derived_timeline_is_monotonic(tmp_path):
    store = _seed(tmp_path / "s")
    out = tmp_path / "out.json"
    export_store(store, out, fmt=OTEL)
    spans = _spans_of(_load(out))
    times = [(int(s["startTimeUnixNano"]), int(s["endTimeUnixNano"]))
             for s in spans]
    # children run back-to-back; the root (first) encloses them all
    for (_, end), (start, _) in itertools.pairwise(times[1:]):
        assert end == start
    root_start, root_end = times[0]
    assert root_start == times[1][0]
    assert root_end == times[-1][1]
    assert root_end - root_start == (1200 + 5 + 300) * 1_000_000
    attrs = {a["key"]: a["value"] for a in spans[1]["attributes"]}
    assert attrs["approximately.time.derived"]["boolValue"] is True


def test_long_text_is_capped(tmp_path):
    trace = Trace(task="t", id="abc", created_at=1.0)
    trace.add(Step(kind="response", result="x" * (_TEXT_CAP + 5000),
                   latency_ms=1))
    spans = trace_to_spans(trace)
    attrs = {a["key"]: a["value"] for a in spans[1]["attributes"]}
    assert len(attrs["approximately.result"]["stringValue"]) == _TEXT_CAP


def test_bytes_are_stable_and_ids_deterministic(tmp_path):
    store = _seed(tmp_path / "s")
    one, two = tmp_path / "1.json", tmp_path / "2.json"
    export_store(store, one, fmt=OTEL)
    export_store(store, two, fmt=OTEL)
    assert one.read_bytes() == two.read_bytes()
    spans = _spans_of(_load(one))
    assert spans[1]["spanId"] != spans[2]["spanId"]


def test_meta_becomes_prefixed_scalars(tmp_path):
    store = _seed(tmp_path / "s")
    out = tmp_path / "out.json"
    export_store(store, out, fmt=OTEL)
    root = _spans_of(_load(out))[0]
    attrs = {a["key"]: a["value"] for a in root["attributes"]}
    assert attrs["approximately.meta.env"]["stringValue"] == "ci"


def test_otel_composes_with_query(tmp_path):
    store = _seed(tmp_path / "s")
    rec = Recorder("water the plants", save=False)
    rec.respond("done", success=True)
    store.save(rec.trace)
    out = tmp_path / "out.json"
    result = export_store(store, out, fmt=OTEL,
                          query_text="success == false")
    assert result["written"] == 1
    spans = _spans_of(_load(out))
    assert len(spans) == 4  # the failed trace only


def test_unknown_format_still_rejected(tmp_path):
    store = _seed(tmp_path / "s")
    try:
        export_store(store, tmp_path / "o", fmt="parquet")
    except ValueError as exc:
        assert "otel" in str(exc)
    else:
        raise AssertionError("parquet accepted")


def test_cli_export_otel(tmp_path, capsys):
    store = _seed(tmp_path / "s")
    out = tmp_path / "out.json"
    args = argparse.Namespace(store=str(store.directory),
                              output=str(out), format="otel",
                              query=None, since=None, dedupe=False,
                              with_annotations=False, json=True)
    assert cmd_export(args) == 0
    env = _load(out)
    assert _spans_of(env)[0]["status"] == {"code": 2}


def test_mcp_export_otel(tmp_path):
    store = _seed(tmp_path / "s")
    out = tmp_path / "out.json"
    payload = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "export_transcripts",
                   "arguments": {"store": str(store.directory),
                                 "output": str(out),
                                 "format": "otel"}},
    }, ServerContext(str(store.directory)))
    result = json.loads(payload["result"]["content"][0]["text"])
    assert result["written"] == 1
    assert result["format"] == "otel"
    assert _spans_of(_load(out))[0]["parentSpanId"] == ""


def test_annotations_ride_root_span_events(tmp_path):
    store = _seed(tmp_path / "s")
    trace = store.list_traces()[0]
    store.annotate(trace.id, "infra timeout confirmed",
                   author="oncall", verdict="confirmed")
    out = tmp_path / "ann.json"
    export_store(store, out, fmt=OTEL)
    env = _load(out)
    root = _spans_of(env)[0]
    events = root["events"]
    assert len(events) == 1
    assert events[0]["name"] == "annotation.confirmed"
    keys = {a["key"]: a["value"] for a in events[0]["attributes"]}
    assert keys["annotation.author"]["stringValue"] == "oncall"
    assert "infra timeout" in keys["annotation.note"]["stringValue"]


def test_no_annotations_no_events_key(tmp_path):
    store = _seed(tmp_path / "s")
    out = tmp_path / "clean.json"
    export_store(store, out, fmt=OTEL)
    root = _spans_of(_load(out))[0]
    assert "events" not in root          # byte-stability preserved
