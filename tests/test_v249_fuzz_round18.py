"""v249: fuzz round 18 — hostile traces at the export doors.

Round contract unchanged: documented errors or clean skips, never a
crash.  The surfaces this round: the CSV door meeting a trace whose
task is None or whose agent name carries newlines and C1 controls,
the OTLP door meeting those same traces, and the query grammar
meeting extreme-but-legal field values.
"""

import csv

from approximately.exporter import export_store
from approximately.query import select
from approximately.recorder import Recorder
from approximately.store import TraceStore
from approximately.trace import Step, Trace


def _rows(path):
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.reader(fh))


def test_csv_survives_none_task_and_weird_agents(tmp_path):
    store = TraceStore(tmp_path / "s")
    rec = Recorder("odd one", store=store, save=False)
    rec.trace.task = None
    rec.trace.model = None
    rec.tool("note", {}, agent="agent\nwith\x0bvertical\ttabs",
             result="fine")
    rec.respond("done", success=True)
    store.save(rec.trace)
    out = tmp_path / "s.csv"
    payload = export_store(store, out, fmt="csv")
    assert payload["written"] == 2
    rows = _rows(out)
    assert rows[1][1] == ""                      # None task → blank
    assert "\n" in rows[1][8]                    # agent preserved, quoted


def test_csv_survives_non_string_results(tmp_path):
    store = TraceStore(tmp_path / "s")
    Recorder("typed", store=store, save=False)
    step = Step(kind="tool_call", tool="calc", tokens=5,
                latency_ms=10)
    step.result = {"answer": 42}                # not a string at all
    trace = Trace(task="typed", id="typed-1")
    trace.add(step)
    trace.add(Step(kind="response", result=7))
    store.save(trace)
    out = tmp_path / "s.csv"
    export_store(store, out, fmt="csv")
    rows = _rows(out)
    assert "42" in rows[1][13]                  # str() of the dict


def test_otel_survives_the_same_hostile_traces(tmp_path):
    store = TraceStore(tmp_path / "s")
    rec = Recorder("hostile", store=store, save=False)
    rec.trace.task = None
    rec.tool("note", {}, agent="nul\x1cagent", result="\x00ish")
    rec.respond("done", success=True)
    store.save(rec.trace)
    out = tmp_path / "s.json"
    payload = export_store(store, out, fmt="otel")
    assert payload["traces"] == 1
    raw = json_load(out)
    spans = raw["resourceSpans"][0]["scopeSpans"][0]["spans"]
    assert len(spans) >= 2                      # root + step


def json_load(path):
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def test_query_extreme_but_legal_values():
    rec = Recorder("x" * 5000, save=False)
    rec.respond("done", success=True)
    traces = [rec.trace]
    assert len(select(traces, "task contains 'x'")) == 1
    assert len(select(traces, "steps >= 1")) == 1


def test_query_unicode_values_match():
    rec = Recorder("预订最便宜的航班", save=False)
    rec.respond("完成", success=True)
    traces = [rec.trace]
    assert len(select(traces, "task contains '航班'")) == 1
    assert len(select(traces, "task endswith '完成'")) == 0  # task≠result


def test_store_roundtrips_the_hostile_trace(tmp_path):
    store = TraceStore(tmp_path / "s")
    rec = Recorder("hostile", store=store, save=False)
    rec.trace.task = None
    rec.tool("note", {}, agent="agent\x1dgroup", result="r")
    rec.respond("done", success=True)
    store.save(rec.trace)
    back = store.load(rec.trace.id)
    assert back is not None
    assert back.task is None
    assert back.steps[0].agent == "agent\x1dgroup"
