"""v151: fleet-mode latency anomalies — the store is the baseline.

A per-trace baseline only knows what one run considered normal. The
store knows what `search` costs everywhere, every day.
`approximately anomalies --all` baselines each tool family across
every trace (MCP `anomalies` with `fleet: true`), so a single 30s
search inside an otherwise boring week stands out immediately — even
though that trace, on its own, looks unremarkable.
"""

import argparse
import json

from approximately.anomaly import detect_fleet_anomalies
from approximately.cli import cmd_anomalies
from approximately.mcp_server import ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed_store(directory, search_ms, n=4):
    store = TraceStore(directory)
    jitter = (0.9, 1.0, 1.05, 0.95, 1.02)
    for i in range(n):
        rec = Recorder(f"boring run {i}", save=False)
        rec.tool("search", {"q": str(i)}, result="hit")
        rec.respond("done", success=True)
        rec.trace.steps[0].latency_ms = int(search_ms * jitter[i % 5])
        store.save(rec.trace)
    return store


def _outlier_run(store, latency=30000):
    rec = Recorder("the slow one", save=False)
    rec.tool("search", {"q": "heavy"}, result="hit")
    rec.respond("done", success=True)
    rec.trace.steps[0].latency_ms = latency
    store.save(rec.trace)
    return rec.trace


def test_fleet_baselines_catch_the_one_slow_search(tmp_path):
    store = _seed_store(tmp_path / "s", 2000)
    outlier = _outlier_run(store)
    anomalies = detect_fleet_anomalies(store.list_traces())
    assert [a.trace_id for a in anomalies] == [outlier.id]
    assert anomalies[0].tool == "search"
    assert anomalies[0].latency_ms == 30000
    assert anomalies[0].median_ms < 2500  # the family, not the trace


def test_per_trace_baseline_misses_it(tmp_path):
    store = _seed_store(tmp_path / "s", 2000)
    outlier = _outlier_run(store, latency=30000)
    per_trace = detect_fleet_anomalies([outlier])
    # judged alone, the trace has one sample — no scale, no finding
    assert per_trace == []


def test_small_families_are_honest_noops(tmp_path):
    store = _seed_store(tmp_path / "s", 2000, n=2)
    _outlier_run(store)
    assert detect_fleet_anomalies(store.list_traces(),
                                  min_samples=5) == []


def test_cli_anomalies_all(tmp_path, capsys):
    store = _seed_store(tmp_path / "s", 2000)
    _outlier_run(store)
    args = argparse.Namespace(store=str(store.directory),
                              trace=None, all=True, per_tool=False,
                              since=None, threshold=3.5, json=True)
    rc = cmd_anomalies(args)
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 1
    assert payload[0]["tool"] == "search"
    assert payload[0]["latency_ms"] == 30000
    assert rc == 1


def test_mcp_anomalies_fleet(tmp_path):
    store = _seed_store(tmp_path / "s", 2000)
    _outlier_run(store)
    ctx = ServerContext(str(store.directory))
    payload = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "anomalies",
                   "arguments": {"fleet": True,
                                 "store": str(store.directory)}},
    }, ctx)
    result = json.loads(payload["result"]["content"][0]["text"])
    assert result["fleet"] is True
    assert result["traces"] == 5
    assert result["count"] == 1
    assert result["anomalies"][0]["latency_ms"] == 30000
