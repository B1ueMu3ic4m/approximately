"""v0.43 — MCP server gains bisect and doctor tools."""

from __future__ import annotations

import io
import json

from approximately.mcp_server import (
    _TOOLS,
    ServerContext,
    handle_request,
    serve,
)
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _rpc(method, params=None, request_id=1):
    msg = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        msg["params"] = params
    return json.dumps(msg)


def _serve(lines, ctx):
    out = io.StringIO()
    served = serve(iter(lines).__next__, out.write, ctx,
                   max_requests=len(lines))
    return out.getvalue(), served


def _store(tmp_path):
    store = TraceStore(str(tmp_path / "traces"))
    for tid, flip in (("m-pass", False), ("m-fail", True)):
        rec = Recorder("ship it", save=False)
        rec.trace.id = tid
        for i in range(4):
            args = ({"path": f"flip{i}.py"} if flip and i >= 2
                    else {"path": f"f{i}.py"})
            text = (f"step {i} BOOM" if flip and i >= 2
                    else f"step {i} ok " + "x" * 60)
            rec.tool("assistant", args, result=text)
        rec.respond("done", success=not flip)
        store.save(rec.trace)
    (store.directory / "broken.json").write_text("{oops", encoding="utf-8")
    return store


def test_tools_list_includes_bisect_and_doctor():
    ctx = ServerContext(".")
    raw, _ = _serve([_rpc("tools/list")], ctx)
    resp = json.loads(raw.strip().splitlines()[0])
    names = [t["name"] for t in resp["result"]["tools"]]
    assert "bisect" in names and "doctor" in names
    assert len(_TOOLS) == len(names)


def test_mcp_bisect_finds_first_fault(tmp_path):
    store = _store(tmp_path)
    ctx = ServerContext(str(store.directory))
    msg = json.loads(_rpc("tools/call", {
        "name": "bisect",
        "arguments": {"trace": "m-fail", "other": "m-pass"},
    }, request_id=7))
    resp = handle_request(msg, ctx)
    payload = json.loads(resp["result"]["content"][0]["text"])
    fault = payload["first_fault"]
    assert fault is not None
    assert fault["a_index"] == 2
    assert fault["similarity"] < 0.5
    assert resp["result"]["isError"] is False


def test_mcp_bisect_no_fault_is_not_error(tmp_path):
    store = _store(tmp_path)
    ctx = ServerContext(str(store.directory))
    msg = json.loads(_rpc("tools/call", {
        "name": "bisect",
        "arguments": {"trace": "m-pass", "other": "m-pass"},
    }))
    resp = handle_request(msg, ctx)
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["first_fault"] is None


def test_mcp_bisect_missing_trace_is_tool_error(tmp_path):
    store = _store(tmp_path)
    ctx = ServerContext(str(store.directory))
    msg = json.loads(_rpc("tools/call", {
        "name": "bisect",
        "arguments": {"trace": "nope", "other": "m-pass"},
    }))
    resp = handle_request(msg, ctx)
    assert resp["result"]["isError"] is True


def test_mcp_doctor_reports_corrupt(tmp_path):
    store = _store(tmp_path)
    ctx = ServerContext(str(store.directory))
    msg = json.loads(_rpc("tools/call", {"name": "doctor",
                                         "arguments": {}}))
    resp = handle_request(msg, ctx)
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["healthy"] is False
    assert "broken.json" in payload["corrupt"]
    assert payload["records"] == 2


def test_mcp_doctor_with_digest_dir(tmp_path):
    store = _store(tmp_path)
    digests = tmp_path / "digests"
    digests.mkdir()
    (digests / "digest-20260918.jsonl").write_text(
        json.dumps({"ts": 0, "stores": [], "worsening": []}) + "\n"
        + '{"torn"',
        encoding="utf-8")
    ctx = ServerContext(str(store.directory))
    msg = json.loads(_rpc("tools/call", {
        "name": "doctor",
        "arguments": {"digest_dir": str(digests)},
    }))
    resp = handle_request(msg, ctx)
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["digest_days"] == 1
    assert payload["torn_lines"] == 1


def test_mcp_attribute_explain_includes_fusion(tmp_path):
    store = _store(tmp_path)
    ctx = ServerContext(str(store.directory))
    msg = json.loads(_rpc("tools/call", {
        "name": "attribute",
        "arguments": {"trace": "m-fail", "explain": True},
    }))
    resp = handle_request(msg, ctx)
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert "fusion_explanation" in payload
    assert "prior log-odds" in payload["fusion_explanation"]


def test_mcp_attribute_without_explain_omits_fusion(tmp_path):
    store = _store(tmp_path)
    ctx = ServerContext(str(store.directory))
    msg = json.loads(_rpc("tools/call", {
        "name": "attribute", "arguments": {"trace": "m-fail"}}))
    resp = handle_request(msg, ctx)
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert "fusion_explanation" not in payload
