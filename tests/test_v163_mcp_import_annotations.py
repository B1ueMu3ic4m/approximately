"""v163: MCP tool #30 — `import_annotations` mirrors the sidecar merge.

The v1.50 handoff pair completes its mirror: an MCP client can merge
an annotation sidecar into the store (append-only, content-keyed),
not just the transcript half. Missing file is a tool error, never a
protocol fault; 30 tools, `tools/list` authoritative.
"""

import json

from approximately.mcp_server import _TOOLS, ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _call(arguments, store_dir="."):
    ctx = ServerContext(store_dir)
    return handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "import_annotations",
                   "arguments": arguments},
    }, ctx)


def test_merge_via_mcp(tmp_path):
    store = TraceStore(tmp_path / "s")
    rec = Recorder("the failing run", save=False)
    rec.respond("gave up", success=False)
    store.save(rec.trace)
    sidecar = tmp_path / "notes.jsonl"
    sidecar.write_text(json.dumps({
        "trace_id": rec.trace.id, "note": "known flake",
        "author": "op", "verdict": "confirmed"}) + "\n",
        encoding="utf-8")
    payload = _call({"path": str(sidecar),
                     "store": str(store.directory)})
    result = json.loads(payload["result"]["content"][0]["text"])
    assert result["added"] == 1
    again = _call({"path": str(sidecar),
                   "store": str(store.directory)})
    again_result = json.loads(again["result"]["content"][0]["text"])
    assert again_result["added"] == 0
    assert len(store.annotations()) == 1


def test_missing_file_is_tool_error(tmp_path):
    payload = _call({"path": str(tmp_path / "nope.jsonl")})
    assert payload["result"]["isError"] is True
    assert "no such file" in json.dumps(payload["result"]["content"])


def test_listed_with_required_path():
    schema = next(t for t in _TOOLS
                  if t["name"] == "import_annotations")
    # path OR glob: either selects the sidecars
    assert schema["inputSchema"]["required"] == []


def test_glob_merges_every_sidecar(tmp_path):
    store = TraceStore(tmp_path / "s")
    rec = Recorder("glob target", save=False)
    rec.respond("done", success=True)
    store.save(rec.trace)
    for i in range(2):
        sidecar = tmp_path / f"part{i}.jsonl"
        sidecar.write_text(json.dumps({
            "trace_id": rec.trace.id, "note": f"note {i}",
            "author": "op", "verdict": "confirmed"}) + "\n",
            encoding="utf-8")
    ctx = ServerContext(str(store.directory))
    payload = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "import_annotations",
                   "arguments": {"glob": str(tmp_path / "*.jsonl"),
                                 "store": str(store.directory)}},
    }, ctx)
    result = json.loads(payload["result"]["content"][0]["text"])
    assert result["added"] == 2
    assert len(store.annotations()) == 2
