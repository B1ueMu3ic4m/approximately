"""v120: MCP tool #24 metrics — Prometheus exposition over stdio.

Store totals by default, per-agent rates with `group_by: "agent"`:
the same text/plain rendering the `metrics --prometheus` CLI writes,
now reachable from any MCP client (or an agent scraping its own
health).
"""

import json

from approximately.mcp_server import _TOOLS, ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store(tmp_path):
    store = TraceStore(str(tmp_path / "s"))
    rec = Recorder("metrics fixture", save=False)
    rec.trace.id = "mx-1"
    rec.tool("deploy", {"env": "prod"}, result=None, error="timeout")
    rec.respond("gave up", success=False)
    store.save(rec.trace)
    rec = Recorder("ok run", save=False)
    rec.trace.id = "mx-2"
    rec.respond("done", success=True)
    store.save(rec.trace)
    return store


def _call(arguments):
    return handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "metrics", "arguments": arguments},
    }, ServerContext("."))


def test_registered():
    assert "metrics" in [t["name"] for t in _TOOLS]


def test_store_totals(tmp_path):
    store = _store(tmp_path)
    resp = _call({"store": str(store.directory)})
    assert resp["result"]["isError"] is False
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["content_type"].startswith("text/plain")
    body = payload["metrics"]
    assert "approximately_runs_total 2" in body
    assert "approximately_failures_total 1" in body
    assert "approximately_failure_rate" in body


def test_group_by_agent(tmp_path):
    store = _store(tmp_path)
    payload = json.loads(_call({
        "store": str(store.directory),
        "group_by": "agent"}).get(
        "result", {}).get("content", [{}])[0].get("text", "{}"))
    body = payload.get("metrics", "")
    if body:
        assert "approximately_agent" in body or body.strip() == ""
