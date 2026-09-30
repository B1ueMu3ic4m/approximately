"""v217: integration round — the seams between the new rounds.

Each recent round tested its own module; this round walks the paths
where they meet: OTLP export→import→export byte-closure, a foreign
backend's spans surviving attribution and the HTML report, token
anomalies on imported traces, and spool feeding a fleet watch that
pages.  Seams are where the bugs live.
"""

import json
from pathlib import Path

from approximately.attributor import attribute
from approximately.exporter import export_store
from approximately.fleet import _should_alert, survey
from approximately.importer import import_file
from approximately.report import render_html
from approximately.spool import spool_pass
from approximately.store import TraceStore
from approximately.trace import Step, Trace


def _recorded_run(store, task="fix the login bug", ident="abc123def456"):
    trace = Trace(task=task, id=ident, created_at=1759275600.123456,
                  model="gpt-x", success=False,
                  final_output="gave up")
    trace.add(Step(kind="plan", thought="run the tests", latency_ms=120))
    for i in range(6):
        trace.add(Step(kind="tool_call", tool="shell",
                       args={"cmd": f"pytest -k case{i}"},
                       result="ok", latency_ms=400 + i * 10,
                       tokens=900 + i * 5))
    trace.add(Step(kind="tool_call", tool="shell",
                   args={"cmd": "pytest -k flaky"}, result="boom",
                   error="exit 1", latency_ms=4000, tokens=12000))
    trace.add(Step(kind="observation", tool="shell", result="boom",
                   error="exit 1", latency_ms=5))
    trace.add(Step(kind="response", result="cannot fix", latency_ms=300))
    store.save(trace)
    return trace


def test_otlp_roundtrip_is_byte_closed(tmp_path):
    source = TraceStore(tmp_path / "src")
    _recorded_run(source)
    outbox = tmp_path / "out"
    outbox.mkdir()
    first = outbox / "one.otlp.json"
    export_store(source, first, fmt="otel")
    back = TraceStore(tmp_path / "back")
    import_file(first, back)
    second = outbox / "two.otlp.json"
    export_store(back, second, fmt="otel")
    assert first.read_bytes() == second.read_bytes(), (
        "export→import→export must close byte-for-byte")


def test_roundtripped_trace_keeps_meaning(tmp_path):
    source = TraceStore(tmp_path / "src")
    original = _recorded_run(source)
    outbox = tmp_path / "out"
    outbox.mkdir()
    export_store(source, outbox / "t.otlp.json", fmt="otel")
    back = TraceStore(tmp_path / "back")
    import_file(outbox / "t.otlp.json", back)
    restored = back.load(original.id)
    assert restored is not None
    assert restored.success is False
    assert restored.final_output == "gave up"
    assert restored.model == "gpt-x"
    assert [s.tokens for s in restored.steps] == \
        [s.tokens for s in original.steps]
    assert restored.steps[1].args == {"cmd": "pytest -k case0"}


def test_roundtripped_trace_attributes_and_renders(tmp_path):
    source = TraceStore(tmp_path / "src")
    _recorded_run(source)
    outbox = tmp_path / "out"
    outbox.mkdir()
    export_store(source, outbox / "t.otlp.json", fmt="otel")
    back = TraceStore(tmp_path / "back")
    import_file(outbox / "t.otlp.json", back)
    trace = back.list_traces()[0]
    report = attribute(trace)
    html = render_html(trace, report, store=back)
    assert html
    assert "approximately" in html or "failure" in html.lower()


def test_foreign_spans_survive_attribution(tmp_path):
    # a tracing backend's export: none of our attributes, a failure
    # status, unfamiliar span names
    document = {"resourceSpans": [{"scopeSpans": [{"spans": [
        {"traceId": "e" * 32, "spanId": "0" * 16, "parentSpanId": "",
         "name": "agent.session",
         "startTimeUnixNano": "1759275600000000000",
         "endTimeUnixNano": "1759275700000000000",
         "status": {"code": 2},
         "attributes": [{"key": "gen_ai.system",
                         "value": {"stringValue": "openai"}}]},
        {"traceId": "e" * 32, "spanId": "1" * 16,
         "parentSpanId": "0" * 16, "name": "tool.web_search",
         "startTimeUnixNano": "1759275601000000000",
         "endTimeUnixNano": "1759275602000000000"},
        {"traceId": "e" * 32, "spanId": "2" * 16,
         "parentSpanId": "0" * 16, "name": "agent.llm_call",
         "startTimeUnixNano": "1759275603000000000",
         "endTimeUnixNano": "1759275609000000000"},
    ]}]}]}
    envelope = tmp_path / "foreign.otlp.json"
    envelope.write_text(json.dumps(document), encoding="utf-8")
    back = TraceStore(tmp_path / "back")
    import_file(envelope, back)
    trace = back.list_traces()[0]
    assert trace.success is False
    assert len(trace.steps) == 2
    assert trace.meta.get("attr.gen_ai.system") == "openai"
    report = attribute(trace)
    html = render_html(trace, report, store=back)
    assert html


def test_imported_tokens_still_flag_burn(tmp_path):
    source = TraceStore(tmp_path / "src")
    _recorded_run(source)
    outbox = tmp_path / "out"
    outbox.mkdir()
    export_store(source, outbox / "t.otlp.json", fmt="otel")
    back = TraceStore(tmp_path / "back")
    import_file(outbox / "t.otlp.json", back)
    trace = back.list_traces()[0]
    from approximately.anomaly import detect_token_anomalies

    anomalies = detect_token_anomalies(trace)
    assert anomalies
    assert anomalies[0].tokens == 12000
    assert anomalies[0].direction == "burn"


def test_spool_feeds_a_pageable_fleet(tmp_path):
    store = TraceStore(tmp_path / "s")
    source = TraceStore(tmp_path / "src")
    _recorded_run(source, ident="failed123456")
    outbox = tmp_path / "out"
    outbox.mkdir()
    export_store(source, outbox / "run.otlp.json", fmt="otel")
    spool = tmp_path / "spool"
    spool.mkdir()
    (spool / "run.otlp.json").write_bytes(
        (outbox / "run.otlp.json").read_bytes())

    result = spool_pass(store, spool)
    assert result["imported"] == 1
    assert result["failed_traces"] == 1     # the gate sees the failure
    summaries = survey([Path(store.directory)])
    assert summaries[0].traces == 1
    assert summaries[0].failure_rate == 1.0
    assert _should_alert(summaries, 0.5) is True
