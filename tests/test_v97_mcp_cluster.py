"""v97: MCP tool #13 — cluster, recidivist modes and agents over stdio.

`cluster` / `cluster --by-agent` existed on the CLI; MCP clients can
now ask "which failure modes keep recurring (and via which tools), or
which agents keep failing" with the same min_size threshold and the
same query-expression filter as every other store tool.
"""

import json

from approximately.mcp_server import _TOOLS, ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store(tmp_path):
    """Two timeouts of search (recidivist mode FM-1.3-ish via one tool),
    one clean run."""
    store = TraceStore(str(tmp_path / "s"))
    for i in range(2):
        rec = Recorder(f"flaky run {i}", save=False)
        rec.tool("search", {"q": str(i)}, result=None, error="timeout",
                 agent="researcher")
        rec.respond("gave up", success=False, agent="researcher")
        store.save(rec.trace)
    rec = Recorder("clean run", save=False)
    rec.tool("search", {"q": "fine"}, result="hit")
    rec.respond("done", success=True)
    store.save(rec.trace)
    return store


def _call(arguments):
    ctx = ServerContext(".")
    return handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "cluster", "arguments": arguments},
    }, ctx)


def test_cluster_registered():
    assert "cluster" in [t["name"] for t in _TOOLS]


def test_cluster_modes(tmp_path):
    resp = _call({"store": str(_store(tmp_path).directory)})
    assert resp["result"]["isError"] is False
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["traces_scanned"] == 3
    assert payload["failures_found"] == 2
    sizes = {c["mode_id"]: c["size"] for c in payload["clusters"]}
    assert any(v >= 2 for v in sizes.values())


def test_cluster_min_size_filters_singletons(tmp_path):
    store = _store(tmp_path)
    rec = Recorder("odd one out", save=False)
    rec.tool("deploy", {}, result=None, error="crash")
    rec.respond("dead", success=False)
    store.save(rec.trace)
    resp = _call({"store": str(store.directory), "min_size": 2})
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert all(c["size"] >= 2 for c in payload["clusters"])
    assert payload["traces_scanned"] == 4


def test_cluster_by_agent(tmp_path):
    resp = _call({"store": str(_store(tmp_path).directory),
                  "by_agent": True})
    payload = json.loads(resp["result"]["content"][0]["text"])
    rows = payload["recidivist_agents"]
    assert [r["agent"] for r in rows] == ["researcher"]
    assert rows[0]["failed_traces"] == 2


def test_cluster_expression_filter(tmp_path):
    resp = _call({"store": str(_store(tmp_path).directory),
                  "expression": "success == false"})
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["traces_scanned"] == 2


def test_cluster_top_n(tmp_path):
    resp = _call({"store": str(_store(tmp_path).directory), "top": 1})
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert len(payload["clusters"]) <= 1


def test_cluster_bad_expression_is_tool_error(tmp_path):
    resp = _call({"store": str(_store(tmp_path).directory),
                  "expression": "nonsense =="})
    assert resp["result"]["isError"] is True
