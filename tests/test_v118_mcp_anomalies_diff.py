"""v118: MCP tools #21 anomalies and #22 diff.

`anomalies` flags per-step latency outliers (modified z-score over
tool-call steps); `diff` gives the structural alignment of two traces
with divergences ranked most-different first. Both are long-standing
CLI surfaces now reachable over stdio.
"""

import json

from approximately.mcp_server import ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store(tmp_path):
    store = TraceStore(str(tmp_path / "s"))
    fast = Recorder("fast run", save=False)
    fast.trace.id = "fast"
    fast.tool("probe", {"i": 0}, result="ok", latency_ms=10.0)
    fast.tool("probe", {"i": 1}, result="ok", latency_ms=12.0)
    fast.respond("done", success=True)
    store.save(fast.trace)
    slow = Recorder("slow run", save=False)
    slow.trace.id = "slow"
    baseline = (11.0, 10.0, 12.0, 13.0, 12.0, 14.0, 900.0)
    tools = []
    for i, _ms in enumerate(baseline):
        tools.append(slow.tool("probe", {"i": i}, result="ok"))
    slow.respond("done", success=True)
    # Recorder times steps itself; tests stamp latencies post hoc
    for step, ms in zip(tools, baseline):
        step.latency_ms = ms
    store.save(slow.trace)
    return store


def _call(name, arguments):
    return handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }, ServerContext("."))


def _payload(resp):
    assert resp["result"]["isError"] is False, resp["result"]
    return json.loads(resp["result"]["content"][0]["text"])


def test_anomalies_flags_outlier(tmp_path):
    store = _store(tmp_path)
    payload = _payload(_call("anomalies", {"trace": "slow",
                                           "store": str(store.directory)}))
    assert payload["trace"] == "slow"
    assert payload["count"] >= 1
    worst = payload["anomalies"][0]
    assert worst["latency_ms"] == 900.0


def test_anomalies_clean_trace(tmp_path):
    store = _store(tmp_path)
    payload = _payload(_call("anomalies", {"trace": "fast",
                                           "store": str(store.directory)}))
    assert payload["count"] == 0


def test_diff_shape_and_similarity(tmp_path):
    store = _store(tmp_path)
    payload = _payload(_call("diff", {"trace": "fast",
                                      "other": "slow",
                                      "store": str(store.directory)}))
    assert payload["a"] == "fast" and payload["b"] == "slow"
    assert 0.0 <= payload["similarity"] <= 1.0
    assert isinstance(payload["divergences"], list)


def test_diff_missing_trace_is_tool_error(tmp_path):
    store = _store(tmp_path)
    resp = _call("diff", {"trace": "fast", "other": "nope",
                          "store": str(store.directory)})
    assert resp["result"]["isError"] is True


def test_similar_cross_store(tmp_path):
    """v0.97: `--other-store` compares across stores - find the
    nearest neighbour in a different project's traces."""
    import argparse

    from approximately.cli import cmd_similar

    store_a = TraceStore(str(tmp_path / "a"))
    rec = Recorder("book the flight", save=False)
    rec.trace.id = "a-1"
    rec.tool("search", {"route": "SFO-NRT"}, result="$880")
    rec.respond("booked", success=True)
    store_a.save(rec.trace)

    store_b = TraceStore(str(tmp_path / "b"))
    for i in range(2):
        rec = Recorder("book the hotel", save=False)
        rec.trace.id = f"b-{i}"
        rec.tool("search_hotel", {"city": "NRT"}, result="$120")
        rec.respond("booked", success=True)
        store_b.save(rec.trace)

    args = argparse.Namespace(store=str(store_a.directory),
                              trace="a-1", other_store=str(
                                  store_b.directory),
                              top=5, json=False)
    assert cmd_similar(args) == 0
