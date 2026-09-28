"""v130: MCP tool #25 — import_transcripts over stdio.

`approximately import` (v1.19) is mirrored into the MCP surface per
the all-commands-`--json` + MCP-mirror rule: an MCP client can now
point at a foreign transcript JSONL on disk and pull it into a
tamper-evident store, with the same sniffing, idempotence and
dry-run semantics as the CLI.
"""

import json

from approximately.mcp_server import _TOOLS, ServerContext, handle_request
from approximately.store import TraceStore


def _call(arguments, store_dir="."):
    ctx = ServerContext(store_dir)
    return handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "import_transcripts",
                   "arguments": arguments},
    }, ctx)


def _text(payload):
    return json.loads(payload["result"]["content"][0]["text"])


def test_listed_in_tools_with_schema():
    names = [t["name"] for t in _TOOLS]
    assert names.count("import_transcripts") == 1
    schema = next(t for t in _TOOLS
                  if t["name"] == "import_transcripts")
    assert schema["inputSchema"]["required"] == ["path"]
    assert "dry_run" in schema["inputSchema"]["properties"]


def test_import_via_mcp(tmp_path):
    path = tmp_path / "runs.jsonl"
    path.write_text(json.dumps({
        "messages": [{"role": "user", "content": "q"},
                     {"role": "assistant", "content": "a"}]}) + "\n",
        encoding="utf-8")
    store_dir = tmp_path / "s"
    payload = _call({"path": str(path), "store": str(store_dir)})
    result = _text(payload)
    assert result["imported"] == 1
    assert TraceStore(str(store_dir)).load(result["trace_ids"][0])


def test_dry_run_and_idempotence_via_mcp(tmp_path):
    path = tmp_path / "runs.jsonl"
    path.write_text(json.dumps({
        "messages": [{"role": "user", "content": "q"},
                     {"role": "assistant", "content": "a"}]}) + "\n",
        encoding="utf-8")
    store_dir = str(tmp_path / "s")
    dry = _text(_call({"path": str(path), "store": store_dir,
                       "dry_run": True}))
    assert dry["imported"] == 1
    assert TraceStore(store_dir).list_traces() == []
    first = _text(_call({"path": str(path), "store": store_dir}))
    again = _text(_call({"path": str(path), "store": store_dir}))
    assert first["imported"] == 1 and again["imported"] == 0


def test_missing_file_is_tool_error_not_crash(tmp_path):
    payload = _call({"path": str(tmp_path / "nope.jsonl"),
                     "store": str(tmp_path / "s")})
    assert payload["result"]["isError"] is True
    assert "no such file" in json.dumps(payload["result"]["content"])
