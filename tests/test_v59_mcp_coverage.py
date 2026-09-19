"""v0.59 — MCP server coverage: missing-trace paths, survey/query
handlers, the generic tool-exception branch, and the CLI entry."""

from __future__ import annotations

import argparse
import io
import json
import sys

from approximately.mcp_server import (
    ServerContext,
    cmd_mcp,
    handle_request,
)
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _rpc(method, params=None, request_id=1):
    msg = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        msg["params"] = params
    return json.dumps(msg)


def _payload(resp):
    return json.loads(resp["result"]["content"][0]["text"])


def _store(tmp_path):
    store = TraceStore(str(tmp_path / "traces"))
    rec = Recorder("probe", save=False)
    rec.trace.id = "mcp-x"
    rec.tool("bash", {"cmd": "ls"}, result="ok")
    rec.respond("done", success=False)
    store.save(rec.trace)
    return store


def test_attribute_missing_trace_is_tool_error(tmp_path):
    ctx = ServerContext(str(_store(tmp_path).directory))
    msg = json.loads(_rpc("tools/call", {
        "name": "attribute", "arguments": {"trace": "ghost"}}))
    resp = handle_request(msg, ctx)
    payload = _payload(resp)
    assert resp["result"]["isError"] is True
    assert "no trace 'ghost'" in payload["error"]


def test_verify_missing_trace_is_tool_error(tmp_path):
    ctx = ServerContext(str(_store(tmp_path).directory))
    msg = json.loads(_rpc("tools/call", {
        "name": "verify", "arguments": {"trace": "ghost"}}))
    resp = handle_request(msg, ctx)
    assert resp["result"]["isError"] is True


def test_verify_existing_trace_returns_verdict(tmp_path):
    ctx = ServerContext(str(_store(tmp_path).directory))
    msg = json.loads(_rpc("tools/call", {
        "name": "verify", "arguments": {"trace": "mcp-x"}}))
    resp = handle_request(msg, ctx)
    payload = _payload(resp)
    assert resp["result"]["isError"] is False
    assert payload["verdict"] in ("intact", "unsigned")


def test_survey_over_store_dir(tmp_path):
    _store(tmp_path)
    ctx = ServerContext(".")
    msg = json.loads(_rpc("tools/call", {
        "name": "survey",
        "arguments": {"stores": [str(tmp_path / "traces")]}}))
    resp = handle_request(msg, ctx)
    payload = _payload(resp)
    assert payload["stores"][0]["traces"] == 1


def test_query_handler_bad_expression_is_tool_error(tmp_path):
    ctx = ServerContext(str(_store(tmp_path).directory))
    msg = json.loads(_rpc("tools/call", {
        "name": "query", "arguments": {"expression": "mode =="}}))
    resp = handle_request(msg, ctx)
    assert resp["result"]["isError"] is True


def test_bisect_missing_other_trace_is_tool_error(tmp_path):
    ctx = ServerContext(str(_store(tmp_path).directory))
    msg = json.loads(_rpc("tools/call", {
        "name": "bisect",
        "arguments": {"trace": "mcp-x", "other": "ghost"}}))
    resp = handle_request(msg, ctx)
    assert resp["result"]["isError"] is True


def test_generic_tool_exception_still_answers(tmp_path, monkeypatch):
    _store(tmp_path)
    ctx = ServerContext(str(tmp_path / "traces"))
    # a non-KeyError failure inside a handler still answers as a tool
    # error payload (never crashes the loop)
    import approximately.mcp_server as m

    def _boom(ctx, args):
        raise ValueError("boom")

    monkeypatch.setitem(m._HANDLERS, "query", _boom)
    msg = json.loads(_rpc("tools/call", {
        "name": "query", "arguments": {"expression": "success == false",
                                       "store": str(tmp_path)}}))
    resp = handle_request(msg, ctx)
    payload = _payload(resp)
    assert resp["result"]["isError"] is True
    assert payload["error"] == "ValueError: boom"


def test_serve_stops_on_empty_string_eof(tmp_path):
    """Some stream wrappers signal EOF with "" rather than raising."""
    from approximately.mcp_server import serve

    calls = {"n": 0}

    def read():
        calls["n"] += 1
        if calls["n"] == 1:
            return json.dumps({"jsonrpc": "2.0", "id": 1,
                               "method": "ping"})
        return ""  # EOF signal

    out = io.StringIO()
    served = serve(read, out.write, ServerContext("."), max_requests=5)
    assert served == 1
    assert calls["n"] == 2


def test_cmd_mcp_serves_scripted_stdio(tmp_path, capsys):
    _store(tmp_path)
    stdin = io.StringIO("".join(
        json.dumps(m) + "\n" for m in [
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            "\n",  # mid-stream blank line: clean shutdown
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ]))
    stdout = io.StringIO()
    args = argparse.Namespace(store=str(tmp_path / "traces"),
                              _stdin=stdin, _stdout=stdout,
                              _max_requests=2, _report=True)
    rc = cmd_mcp(args)
    assert rc == 0
    lines = [json.loads(row) for row in
             stdout.getvalue().splitlines() if row.strip()]
    assert len(lines) == 2 and lines[0]["result"] == {}
    assert "served 2 request(s)" in capsys.readouterr().err


def test_cmd_mcp_default_streams_are_std(tmp_path, monkeypatch,
                                         capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    args = argparse.Namespace(store=str(tmp_path),
                              _max_requests=0, _report=False)
    assert cmd_mcp(args) == 0
