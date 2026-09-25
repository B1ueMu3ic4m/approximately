"""v100: MCP tools #14 similar and #15 drift.

The CLI's `similar` (alignment-nearest traces) and `drift` (PSI
between the oldest and newest windows) become stdio tools, closing
the last CLI/MCP surface gaps: an MCP client can now ask "what does
this run look like?" and "is the fleet's behaviour shifting?".
"""

import json

from approximately.mcp_server import _TOOLS, ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store(tmp_path):
    store = TraceStore(str(tmp_path / "s"))
    for i in range(6):
        rec = Recorder(f"search task {i}", save=False)
        rec.trace.id = f"s-{i}"
        rec.tool("search", {"q": i}, result=f"hit {i}",
                 error=None if i % 2 else "timeout")
        rec.respond("done", success=bool(i % 2))
        store.save(rec.trace)
    return store


def _call(name, arguments):
    return handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }, ServerContext("."))


def _payload(resp):
    assert resp["result"]["isError"] is False, resp["result"]
    return json.loads(resp["result"]["content"][0]["text"])


def test_registered():
    names = [t["name"] for t in _TOOLS]
    assert "similar" in names and "drift" in names


def test_similar_ranks_neighbours(tmp_path):
    store = _store(tmp_path)
    payload = _payload(_call("similar", {"trace": "s-0",
                                         "store": str(store.directory)}))
    assert payload["trace"] == "s-0"
    assert 0 < len(payload["matches"]) <= 5
    scores = [m["similarity"] for m in payload["matches"]]
    assert scores == sorted(scores, reverse=True)
    assert all(m["id"] != "s-0" for m in payload["matches"])


def test_similar_top_and_missing_trace(tmp_path):
    store = _store(tmp_path)
    payload = _payload(_call("similar", {"trace": "s-1",
                                         "store": str(store.directory),
                                         "top": 2}))
    assert len(payload["matches"]) <= 2
    resp = _call("similar", {"trace": "nope",
                             "store": str(store.directory)})
    assert resp["result"]["isError"] is True


def test_drift_windows_and_psi(tmp_path):
    store = _store(tmp_path)
    payload = _payload(_call("drift", {"store": str(store.directory)}))
    assert isinstance(payload["psi"], float)
    assert payload["verdict"]
    assert payload["baseline_actions"] > 0
    assert payload["current_actions"] > 0
    for row in payload["top_shifted"]:
        assert 0.0 <= row["baseline_share"] <= 1.0
        assert 0.0 <= row["current_share"] <= 1.0


def test_drift_baseline_ratio(tmp_path):
    store = _store(tmp_path)
    payload = _payload(_call("drift", {"store": str(store.directory),
                                       "baseline_ratio": 0.8}))
    # 80% of 6 = 4 baseline, 2 current traces -> actions split
    assert payload["baseline_actions"] >= payload["current_actions"]


def test_drift_needs_both_windows(tmp_path):
    store = TraceStore(str(tmp_path / "tiny"))
    rec = Recorder("only one", save=False)
    rec.respond("done", success=True)
    rec.trace.id = "only"
    store.save(rec.trace)
    resp = _call("drift", {"store": str(store.directory)})
    assert resp["result"]["isError"] is True
