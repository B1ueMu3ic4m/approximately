"""v141: export --since + MCP tool #27 scan_tool.

`export --since DAYS` mirrors list_traces' age window onto the export
path (yesterday's failures to a friend without the whole store). The
toolscan finally mirrors into MCP per the ops-pair rule: an agent
stack can check a tool description before wiring it in, passing a
file path or the text inline.
"""

import argparse
import json
import time

from approximately.cli import cmd_export
from approximately.exporter import export_store
from approximately.mcp_server import ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed(directory, task, age_days=0.0):
    store = TraceStore(directory)
    rec = Recorder(task, save=False)
    rec.respond("done", success=True)
    store.save(rec.trace)
    if age_days:
        trace = rec.trace
        trace.created_at = time.time() - age_days * 86400
        store.save(trace)
    return store


def test_export_since_window(tmp_path):
    store = _seed(tmp_path / "s", "old run", age_days=30)
    _seed(tmp_path / "s", "new run")
    out = tmp_path / "recent.jsonl"
    result = export_store(store, out, since_days=7)
    assert result["written"] == 1
    rows = [json.loads(line) for line in
            out.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["metadata"]["task"] == "new run"


def test_cli_export_since(tmp_path, capsys):
    _seed(tmp_path / "s", "old run", age_days=30)
    _seed(tmp_path / "s", "fresh run")
    args = argparse.Namespace(store=str(tmp_path / "s"),
                              output=str(tmp_path / "out.jsonl"),
                              format="openai-jsonl", query=None,
                              since=7, json=True)
    assert cmd_export(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["written"] == 1


def _call(name, arguments, store_dir="."):
    ctx = ServerContext(store_dir)
    return handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }, ctx)


def test_mcp_scan_tool_inline_text(tmp_path):
    payload = _call("scan_tool", {
        "text": "Use the `ls` tool to list files."})
    result = json.loads(payload["result"]["content"][0]["text"])
    assert result["verdict"] in ("clean", "suspicious", "malicious")
    assert isinstance(result["findings"], list)


def test_mcp_scan_tool_file_and_missing(tmp_path):
    path = tmp_path / "tool.md"
    path.write_text("# cat\nPrints a file.\n", encoding="utf-8")
    payload = _call("scan_tool", {"file": str(path)})
    result = json.loads(payload["result"]["content"][0]["text"])
    assert "verdict" in result
    bad = _call("scan_tool", {"file": str(tmp_path / "nope.md")})
    assert bad["result"]["isError"] is True


def test_mcp_scan_tool_requires_input(tmp_path):
    payload = _call("scan_tool", {})
    assert payload["result"]["isError"] is True
    assert "file" in json.dumps(payload["result"]["content"])


def test_scan_tool_listed_in_tools():
    from approximately.mcp_server import _TOOLS

    schema = next(t for t in _TOOLS if t["name"] == "scan_tool")
    props = schema["inputSchema"]["properties"]
    assert "file" in props and "text" in props
