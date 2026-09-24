"""v89: MCP tool #12 — scoreboard, the agent wave over stdio.

`stats --by-agent` / `cluster --by-agent` existed on the CLI; MCP
clients can now pull the same per-agent rollup, optionally filtered
by any query expression (including `agents contains ...`), with an
optional top-N.
"""

import json

from approximately.mcp_server import _TOOLS, ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _crew_store(tmp_path):
    store = TraceStore(str(tmp_path / "s"))
    for i, ok in enumerate([True, False]):
        rec = Recorder(f"run {i}", save=False)
        rec.tool("search", {"q": str(i)}, result="y", agent="researcher",
                 error=None if ok else "timeout")
        rec.respond("done", success=ok, agent="lead")
        store.save(rec.trace)
    solo = Recorder("solo", save=False)
    solo.respond("fine")
    store.save(solo.trace)
    return store


def _call(arguments, request_id=1):
    ctx = ServerContext(".")
    return handle_request({
        "jsonrpc": "2.0", "id": request_id, "method": "tools/call",
        "params": {"name": "scoreboard", "arguments": arguments},
    }, ctx)


def test_scoreboard_registered():
    assert "scoreboard" in [t["name"] for t in _TOOLS]


def test_scoreboard_full_rollup(tmp_path):
    store = _crew_store(tmp_path)
    resp = _call({"store": str(store.directory)})
    assert resp["result"]["isError"] is False
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["traces_scanned"] == 3
    rows = {r["agent"]: r for r in payload["agents"]}
    assert rows["researcher"]["tool_calls"] == 2
    assert rows["researcher"]["errors"] == 1
    assert rows["researcher"]["failure_rate"] == 0.5
    assert "unattributed" in rows


def test_scoreboard_expression_filter(tmp_path):
    store = _crew_store(tmp_path)
    resp = _call({"store": str(store.directory),
                  "expression": "success == false"})
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["traces_scanned"] == 1
    rows = {r["agent"]: r for r in payload["agents"]}
    assert rows["lead"]["failed_traces"] == 1
    assert rows["lead"]["failure_rate"] == 1.0


def test_scoreboard_top_n(tmp_path):
    store = _crew_store(tmp_path)
    resp = _call({"store": str(store.directory), "top": 1})
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert len(payload["agents"]) == 1


def test_scoreboard_bad_expression_is_tool_error(tmp_path):
    store = _crew_store(tmp_path)
    resp = _call({"store": str(store.directory),
                  "expression": "agents >>> 3"})
    assert resp["result"]["isError"] is True
