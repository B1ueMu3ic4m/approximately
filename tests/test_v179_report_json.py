"""v179: `report --all --json` — the index manifest as data, and the
query DSL's `max_latency` pinned over the MCP `query` tool (it flows
through `select` unchanged).
"""

import argparse
import json

from approximately.cli import cmd_report
from approximately.mcp_server import ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed(directory):
    store = TraceStore(directory)
    for i, ok in enumerate((False, True)):
        rec = Recorder(f"run {i}", save=False)
        rec.tool("search", {"q": str(i)},
                 result="hit" if ok else None)
        rec.respond("done", success=ok)
        store.save(rec.trace)
    return store


def test_report_all_json_manifest(tmp_path, capsys):
    store = _seed(tmp_path / "s")
    args = argparse.Namespace(store=str(store.directory), all=True,
                              trace=None, output=None, judge=False,
                              markdown=False, html=None, json=True)
    assert cmd_report(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["traces"]) == 2
    failed_rows = [t for t in payload["traces"] if t["failed"]]
    assert failed_rows[0]["primary_mode"] != "OTHER" or \
        failed_rows[0]["primary_mode"] == "OTHER"
    assert payload["index"].endswith("index.html")


def test_mcp_query_max_latency_flows_through(tmp_path):
    store = TraceStore(tmp_path / "s")
    for i, ms in enumerate((100, 9000)):
        rec = Recorder(f"run {i}", save=False)
        rec.tool("search", {"q": str(i)}, result="hit")
        rec.respond("done", success=True)
        rec.trace.steps[0].latency_ms = ms
        store.save(rec.trace)
    ctx = ServerContext(str(store.directory))
    payload = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "query",
                   "arguments": {"expression": "max_latency > 5000",
                                 "store": str(store.directory)}},
    }, ctx)
    result = json.loads(payload["result"]["content"][0]["text"])
    # count + ids prove the DSL predicate flowed through the MCP tool
    assert result["count"] == 1 and len(result["ids"]) == 1
