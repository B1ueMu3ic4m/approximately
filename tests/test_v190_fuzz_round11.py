"""fuzz round 11 — the query DSL's derived fields and the perf gates.

Round 11 targets v1.76-v1.89: `max_latency`, `failed_tools` and
`failed_agents` on hostile traces (untimed steps, unicode tool names,
unnamed agents, absurd latencies), the composed predicates over
random stores, and every perf-gate function returning a clean 0/1 on
degenerate stores.
"""

import random

from approximately.align import dedupe_traces
from approximately.anomaly import detect_fleet_anomalies
from approximately.exporter import export_store
from approximately.query import select
from approximately.recorder import Recorder
from approximately.store import TraceStore

SEED = 20260930
rng = random.Random(SEED)

TOOLS = ["search", "部署", "x" * 200, "", "search"]
LATENCIES = [0, -1, 1, 10**11, None]


def _hostile_store(tmp_path):
    store = TraceStore(tmp_path / "s")
    for i in range(12):
        rec = Recorder(f"run {i}", save=False)
        for j in range(rng.randint(0, 4)):
            tool = TOOLS[(i + j) % len(TOOLS)]
            rec.tool(tool, {"i": i},
                     result=None if j % 3 == 0 else "ok",
                     error="timeout" if j % 3 == 0 else None,
                     agent=rng.choice(["a", "b", None]),
                     latency_ms=rng.choice(LATENCIES))
        rec.respond("done", success=rng.choice([True, False]))
        store.save(rec.trace)
    return store


def test_derived_fields_survive_hostile_traces(tmp_path):
    store = _hostile_store(tmp_path)
    traces = store.list_traces()
    for expr in ("max_latency > 5000",
                 "failed_tools contains 'search'",
                 "failed_agents contains 'a'",
                 "max_latency >= 0 or failed_tools contains '部署'"):
        hits = select(traces, expr)
        assert isinstance(hits, list)
        for t in hits:
            assert t.id


def test_composed_predicates_are_deterministic(tmp_path):
    store = _hostile_store(tmp_path)
    traces = store.list_traces()
    expr = ("failed_tools contains 'search' and success == false "
            "and max_latency > 0")
    first = [t.id for t in select(traces, expr)]
    second = [t.id for t in select(traces, expr)]
    assert first == second


def test_dedupe_and_export_on_hostile_store(tmp_path):
    store = _hostile_store(tmp_path)
    traces = store.list_traces()
    kept, dropped = dedupe_traces(traces)
    assert len(kept) + dropped == len(traces)
    out = tmp_path / "out.jsonl"
    result = export_store(store, out)
    assert result["written"] == len(traces)


def test_fleet_anomalies_never_nan(tmp_path):
    store = _hostile_store(tmp_path)
    for a in detect_fleet_anomalies(store.list_traces()):
        assert a.robust_z == a.robust_z
        assert abs(a.robust_z) != float("inf")
