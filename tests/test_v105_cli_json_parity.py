"""v105: CLI --json parity for similar / drift / counterfactual /
predict — the CLI and the MCP tool now render the SAME payload from
shared *_payload() constructors in the library modules.

Before, MCP returned structured data while the CLI only printed
prose; a CI job shelling the CLI had to parse text. Now both answer
with one object per query, byte-for-byte the same fields.
"""

import argparse
import json

from approximately.cli import cmd_counterfactual, cmd_drift, cmd_predict, cmd_similar
from approximately.mcp_server import ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store(tmp_path):
    store = TraceStore(str(tmp_path / "s"))
    for i in range(6):
        rec = Recorder(f"deploy task {i}", save=False)
        rec.trace.id = f"p-{i}"
        ok = i % 2 == 1
        rec.tool("deploy", {"env": "prod"}, result="ok" if ok else None,
                 error=None if ok else "timeout")
        rec.respond("done", success=ok)
        store.save(rec.trace)
    return store


def _cli_args(store, **kw):
    return argparse.Namespace(store=str(store.directory),
                              since=None, json=True, **kw)


def _mcp(name, arguments):
    resp = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }, ServerContext("."))
    assert resp["result"]["isError"] is False, resp["result"]
    return json.loads(resp["result"]["content"][0]["text"])


def test_similar_cli_json_equals_mcp(tmp_path, capsys):
    store = _store(tmp_path)
    args = _cli_args(store, trace="p-0", top=3)
    assert cmd_similar(args) == 0
    cli = json.loads(capsys.readouterr().out)
    mcp = _mcp("similar", {"trace": "p-0",
                           "store": str(store.directory), "top": 3})
    assert cli == mcp
    assert cli["trace"] == "p-0"
    assert len(cli["matches"]) == 3


def test_drift_cli_json_equals_mcp(tmp_path, capsys):
    store = _store(tmp_path)
    args = argparse.Namespace(store=str(store.directory), json=True,
                              baseline_ratio=0.5)
    assert cmd_drift(args) == 0
    cli = json.loads(capsys.readouterr().out)
    mcp = _mcp("drift", {"store": str(store.directory),
                         "baseline_ratio": 0.5})
    assert cli == mcp
    assert "psi" in cli and "verdict" in cli


def test_counterfactual_cli_json_equals_mcp(tmp_path, capsys):
    store = _store(tmp_path)
    args = argparse.Namespace(store=str(store.directory), json=True,
                              trace="p-0")
    assert cmd_counterfactual(args) == 0
    cli = json.loads(capsys.readouterr().out)
    mcp = _mcp("counterfactual", {"trace": "p-0",
                                  "store": str(store.directory)})
    assert cli == mcp
    assert cli["trace"] == "p-0"
    assert isinstance(cli["interventions"], list)


def test_predict_cli_json_equals_mcp(tmp_path, capsys):
    store = _store(tmp_path)
    args = argparse.Namespace(store=str(store.directory), json=True,
                              trace="p-0")
    assert cmd_predict(args) == 0
    cli = json.loads(capsys.readouterr().out)
    mcp = _mcp("predict", {"trace": "p-0",
                           "store": str(store.directory)})
    assert cli == mcp
    assert 0.0 <= cli["probability"] <= 1.0
