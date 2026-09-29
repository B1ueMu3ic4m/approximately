"""v191: `cluster --query` — cluster the failures you care about.

The shared query DSL now filters before clustering: `cluster --query
"tools contains deploy"` answers "which failure modes keep recurring *on
deploy runs*" instead of clustering the whole store. Mirrored into
the MCP `cluster` tool as the `query` parameter.
"""

import argparse
import json

from approximately.cli import cmd_cluster
from approximately.mcp_server import ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed(directory):
    store = TraceStore(directory)
    for i in range(3):
        rec = Recorder(f"deploy run {i}", save=False)
        rec.tool("deploy", {"env": "prod"}, result=None,
                 error="timeout")
        rec.respond("gave up", success=False)
        store.save(rec.trace)
    for i in range(4):
        rec = Recorder(f"search run {i}", save=False)
        rec.tool("search", {"q": str(i)}, result=None, error="timeout")
        rec.respond("gave up", success=False)
        store.save(rec.trace)
    return store


def test_cluster_query_filters_first(tmp_path, capsys):
    store = _seed(tmp_path / "s")
    args = argparse.Namespace(store=str(store.directory), since=None,
                              last=None,
                              query="tools contains deploy",
                              by_agent=False, min_size=2, json=True)
    assert cmd_cluster(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["traces_scanned"] == 3
    assert payload["clusters"][0]["tools"] == ["deploy"]


def test_mcp_cluster_query(tmp_path):
    store = _seed(tmp_path / "s")
    ctx = ServerContext(str(store.directory))
    payload = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "cluster",
                   "arguments": {"store": str(store.directory),
                                 "expression": "tools contains deploy",
                                 "min_size": 2}},
    }, ctx)
    result = json.loads(payload["result"]["content"][0]["text"])
    assert result["traces_scanned"] == 3

