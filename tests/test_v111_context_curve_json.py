"""v111: `context --json` / `curve --json` — CLI and MCP (#18/#19)
render the identical payload from shared constructors in the library.
"""

import argparse
import json

from approximately.cli import cmd_context, cmd_curve
from approximately.mcp_server import ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store(tmp_path):
    store = TraceStore(str(tmp_path / "s"))
    rec = Recorder("json fixture", save=False)
    rec.trace.id = "j-1"
    for i in range(4):
        rec.tool("probe", {"i": i},
                 result=f"flight JT-{i}: SFO-NRT 06-1{i} $8{i}0")
    rec.respond("booked JT-2", success=True)
    store.save(rec.trace)
    return store


def _mcp(name, arguments):
    resp = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }, ServerContext("."))
    assert resp["result"]["isError"] is False, resp["result"]
    return json.loads(resp["result"]["content"][0]["text"])


def test_context_cli_json_equals_mcp(tmp_path, capsys):
    store = _store(tmp_path)
    args = argparse.Namespace(store=str(store.directory), trace="j-1",
                              json=True, facts=None, budget=300)
    assert cmd_context(args) == 0
    cli = json.loads(capsys.readouterr().out)
    mcp = _mcp("context", {"trace": "j-1",
                           "store": str(store.directory), "budget": 300})
    assert cli == mcp
    assert cli["budget"] == 300
    assert 0.0 <= cli["final_recall"] <= 1.0


def test_curve_cli_json_equals_mcp(tmp_path, capsys):
    store = _store(tmp_path)
    args = argparse.Namespace(store=str(store.directory), trace="j-1",
                              json=True, budgets=None, scatter=False,
                              output=None)
    assert cmd_curve(args) == 0
    cli = json.loads(capsys.readouterr().out)
    mcp = _mcp("curve", {"trace": "j-1",
                         "store": str(store.directory)})
    assert cli == mcp
    recalls = [p["recall"] for p in cli["points"]]
    assert recalls == sorted(recalls)
    assert not (tmp_path / "j-1.curve.html").exists(), \
        "--json must not write the HTML page"
