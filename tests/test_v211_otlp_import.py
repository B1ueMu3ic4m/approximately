"""v211: `import --format otel` — the OTel loop closes.

v210 sent traces out as OTLP spans; this round takes them back in.
Our own exports roundtrip idempotently (the original id rides the
``approximately.trace.id`` attribute); a tracing backend's export is
recognized by sniffing, and foreign spans still become recordable
steps instead of being dropped.
"""

import argparse
import json

from approximately.cli import cmd_import
from approximately.exporter import export_store
from approximately.importer import (
    _FORMATS,
    OTEL,
    import_file,
    import_lines,
    otlp_to_traces,
    sniff_format,
)
from approximately.mcp_server import ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed(directory):
    store = TraceStore(directory)
    rec = Recorder("fix the login bug", save=False)
    rec.tool("shell", {"cmd": "pytest"}, result="3 failed",
             error=None)
    rec.respond("cannot fix", success=False)
    store.save(rec.trace)
    return store


def _export(store, tmp_path):
    out = tmp_path / "t.otlp.json"
    export_store(store, out, fmt="otel")
    return out


def test_sniff_and_roundtrip(tmp_path):
    store = _seed(tmp_path / "s")
    out = _export(store, tmp_path)
    assert sniff_format(out) == OTEL
    back_store = TraceStore(tmp_path / "back")
    result = import_file(out, back_store)
    assert result["format"] == OTEL
    assert result["imported"] == 1
    back = back_store.list_traces()[0]
    original = store.list_traces()[0]
    assert back.id == original.id
    assert back.task == original.task
    assert back.success is False
    assert len(back.steps) == len(original.steps)
    tools = [s.tool for s in back.steps if s.kind == "tool_call"]
    assert tools == ["shell"]


def test_reimport_is_a_no_op(tmp_path):
    store = _seed(tmp_path / "s")
    out = _export(store, tmp_path)
    back_store = TraceStore(tmp_path / "back")
    import_file(out, back_store)
    again = import_file(out, back_store)
    assert again["imported"] == 0
    assert again["duplicates"] == 1
    assert len(back_store.list_traces()) == 1


def test_pretty_printed_document(tmp_path):
    store = _seed(tmp_path / "s")
    out = _export(store, tmp_path)
    pretty = tmp_path / "pretty.json"
    pretty.write_text(
        json.dumps(json.loads(out.read_text(encoding="utf-8")),
                   indent=2), encoding="utf-8")
    back_store = TraceStore(tmp_path / "back")
    result = import_file(pretty, back_store)
    assert result["imported"] == 1
    back = back_store.list_traces()[0]
    assert back.id == store.list_traces()[0].id


def test_one_pass_stream_sniff(tmp_path):
    store = _seed(tmp_path / "s")
    out = _export(store, tmp_path)

    def stream():
        yield from out.read_text(encoding="utf-8").splitlines(True)

    result = import_lines(stream(), TraceStore(tmp_path / "back"))
    assert result["format"] == OTEL
    assert result["imported"] == 1


def test_foreign_spans_become_steps(tmp_path):
    document = {"resourceSpans": [{"scopeSpans": [{"spans": [
        {"traceId": "f" * 32, "spanId": "1" * 16,
         "parentSpanId": "", "name": "agent run",
         "startTimeUnixNano": "1000000000",
         "endTimeUnixNano": "2000000000",
         "status": {"code": 2}},
        {"traceId": "f" * 32, "spanId": "2" * 16,
         "parentSpanId": "1" * 16, "name": "db.query",
         "startTimeUnixNano": "1100000000",
         "endTimeUnixNano": "1500000000"},
    ]}]}]}
    traces, malformed, seen, truncated = otlp_to_traces(document)
    assert (malformed, seen, truncated) == (0, 2, 0)
    trace = traces[0]
    assert trace.success is False
    assert trace.task == "agent run"
    assert trace.created_at == 1.0
    assert [s.meta.get("span_name") for s in trace.steps] == \
        ["db.query"]
    # deterministic id: re-parsing yields the same trace id
    again, _, _, _ = otlp_to_traces(document)
    assert again[0].id == trace.id


def test_malformed_envelope_is_loud(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    try:
        import_file(bad, TraceStore(tmp_path / "back"))
    except ValueError as exc:
        assert "JSON" in str(exc)
    else:
        raise AssertionError("garbage accepted silently")


def test_malformed_spans_are_counted(tmp_path):
    document = {"resourceSpans": [{"scopeSpans": [{"spans": [
        {"traceId": "a" * 32, "spanId": "1" * 16,
         "parentSpanId": "", "name": "run"},
        {"name": "no trace id"},
    ]}]}]}
    traces, malformed, seen, truncated = otlp_to_traces(document)
    assert len(traces) == 1
    assert (malformed, seen, truncated) == (1, 2, 0)


def test_not_an_envelope_is_rejected(tmp_path):
    (tmp_path / "x.json").write_text('{"hello": "world"}',
                                     encoding="utf-8")
    try:
        import_file(tmp_path / "x.json", TraceStore(tmp_path / "b"),
                    fmt="otel")
    except ValueError as exc:
        assert "resourceSpans" in str(exc)
    else:
        raise AssertionError("non-OTLP accepted as otel")


def test_status_mapping(tmp_path):
    def doc(code):
        return {"resourceSpans": [{"scopeSpans": [{"spans": [
            {"traceId": "a" * 32, "spanId": "1" * 16,
             "parentSpanId": "", "name": "run",
             "status": {"code": code}}]}]}]}

    for code, expected in ((2, False), (1, True), (0, None)):
        (traces, _, _, _) = otlp_to_traces(doc(code))
        assert traces[0].success is expected
    traces, _, _, _ = otlp_to_traces(doc("not-a-number"))
    assert traces[0].success is None


def test_unknown_format_still_rejected(tmp_path):
    try:
        import_lines(["{}"], TraceStore(tmp_path / "b"), fmt="csv")
    except ValueError as exc:
        assert "otel" in str(exc)
    else:
        raise AssertionError("csv accepted")


def test_cli_import_otel(tmp_path, capsys):
    store = _seed(tmp_path / "s")
    out = _export(store, tmp_path)
    args = argparse.Namespace(
        store=str(tmp_path / "back"), files=[str(out)],
        format="otel", dry_run=False, jobs=1, annotations=False,
        json=True)
    assert cmd_import(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["imported"] == 1
    assert payload["per_file"][0]["format"] == "otel"


def test_mcp_import_otel(tmp_path):
    store = _seed(tmp_path / "s")
    out = _export(store, tmp_path)
    payload = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "import_transcripts",
                   "arguments": {"store": str(tmp_path / "back"),
                                 "path": str(out),
                                 "format": "otel"}},
    }, ServerContext(str(tmp_path / "back")))
    result = json.loads(payload["result"]["content"][0]["text"])
    assert result["imported"] == 1


def test_import_export_fixpoint(tmp_path):
    # export -> import -> export must be stable: the second export
    # parses to the same document as the first
    store = _seed(tmp_path / "s")
    first = _export(store, tmp_path)
    back_store = TraceStore(tmp_path / "back")
    import_file(first, back_store)
    second = tmp_path / "second.otlp.json"
    export_store(back_store, second, fmt="otel")
    spans_a = json.loads(first.read_text(encoding="utf-8"))
    spans_b = json.loads(second.read_text(encoding="utf-8"))
    names_a = [s["name"] for s in
               spans_a["resourceSpans"][0]["scopeSpans"][0]["spans"]]
    names_b = [s["name"] for s in
               spans_b["resourceSpans"][0]["scopeSpans"][0]["spans"]]
    assert names_a == names_b


def test_format_pin():
    assert OTEL in _FORMATS
