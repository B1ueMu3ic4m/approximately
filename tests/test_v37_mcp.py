"""v0.37: zero-dependency MCP stdio server.

JSON-RPC 2.0 over line-delimited stdio: initialize handshake,
tools/list, tools/call over a real store, protocol error codes, and
malformed-input resilience — all through the in-memory serve() loop.
"""

from __future__ import annotations

import io
import json

import pytest

from approximately.mcp_server import (
    MAX_LINE,
    ServerContext,
    handle_request,
    serve,
)
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _rpc(method: str, params=None, request_id=1) -> str:
    msg = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        msg["params"] = params
    return json.dumps(msg)


def _serve(lines, ctx, tmp_path=None):
    out = io.StringIO()
    served = serve(iter(lines).__next__, out.write, ctx,
                   max_requests=len(lines))
    return out.getvalue(), served


def _response_lines(raw: str):
    return [json.loads(line) for line in raw.strip().splitlines()]


class TestProtocol:
    def test_initialize_handshake(self):
        raw, served = _serve([_rpc("initialize")], ServerContext("."))
        resp = _response_lines(raw)[0]
        assert resp["id"] == 1
        assert resp["result"]["protocolVersion"] == "2024-11-05"
        assert resp["result"]["serverInfo"]["name"] == "approximately"
        assert served == 1

    def test_ping(self):
        raw, _ = _serve([_rpc("ping")], ServerContext("."))
        assert _response_lines(raw)[0]["result"] == {}

    def test_notifications_get_no_response(self):
        raw, served = _serve(
            [json.dumps({"jsonrpc": "2.0", "method":
                         "notifications/initialized"})],
            ServerContext("."))
        assert raw == "" and served == 0

    def test_unknown_method_is_32601(self):
        raw, _ = _serve([_rpc("resources/list")], ServerContext("."))
        assert _response_lines(raw)[0]["error"]["code"] == -32601

    def test_malformed_json_is_32700_and_survives(self):
        lines = ["{not json", _rpc("ping")]
        out = io.StringIO()
        it = iter(lines)
        serve(it.__next__, out.write, ServerContext("."), max_requests=2)
        responses = _response_lines(out.getvalue())
        assert responses[0]["error"]["code"] == -32700
        assert responses[1]["id"] == 1

    def test_oversized_line_rejected(self):
        out = io.StringIO()
        serve(iter(["x" * (MAX_LINE + 10)]).__next__, out.write,
              ServerContext("."), max_requests=1)
        assert _response_lines(out.getvalue())[0]["error"]["code"] == \
            -32600

    def test_envelope_error_is_32600(self):
        raw, _ = _serve([json.dumps({"id": 5, "method": "ping"})],
                        ServerContext("."))
        assert _response_lines(raw)[0]["error"]["code"] == -32600


class TestTools:
    def test_tools_list_shape(self):
        raw, _ = _serve([_rpc("tools/list")], ServerContext("."))
        tools = _response_lines(raw)[0]["result"]["tools"]
        names = {t["name"] for t in tools}
        assert {"list_traces", "attribute", "verify", "survey",
                "query"} <= names
        for tool in tools:
            assert "description" in tool and "inputSchema" in tool

    def test_list_traces_over_store(self, tmp_path):
        store = TraceStore(str(tmp_path))
        rec = Recorder("fix the thing", save=False)
        rec.plan("plan it")
        rec.tool("assistant", {}, result="did the thing")
        rec.respond("done", success=True)
        store.save(rec.trace)
        params = {"name": "list_traces",
                  "arguments": {"store": str(tmp_path), "limit": 10}}
        raw, _ = _serve([_rpc("tools/call", params)],
                        ServerContext("."))
        result = _response_lines(raw)[0]["result"]
        assert result["isError"] is False
        payload = json.loads(result["content"][0]["text"])
        assert payload["traces"][0]["task"] == "fix the thing"

    def test_attribute_tool(self, tmp_path):
        store = TraceStore(str(tmp_path))
        rec = Recorder("the task", save=False)
        rec.tool("mutator", {"path": "x.py"}, result="wrote x.py")
        rec.respond("done", success=True)
        store.save(rec.trace)
        params = {"name": "attribute",
                  "arguments": {"trace": rec.trace.id,
                                "store": str(tmp_path)}}
        raw, _ = _serve([_rpc("tools/call", params)], ServerContext("."))
        result = _response_lines(raw)[0]["result"]
        payload = json.loads(result["content"][0]["text"])
        assert "primary_mode" in payload
        assert isinstance(payload["detections"], list)

    def test_missing_trace_reports_tool_error(self, tmp_path):
        params = {"name": "verify",
                  "arguments": {"trace": "nope",
                                "store": str(tmp_path)}}
        raw, _ = _serve([_rpc("tools/call", params)], ServerContext("."))
        result = _response_lines(raw)[0]["result"]
        assert result["isError"] is True
        assert "error" in result["content"][0]["text"]

    def test_unknown_tool_is_32602(self):
        raw, _ = _serve([_rpc("tools/call", {"name": "explode"})],
                        ServerContext("."))
        assert _response_lines(raw)[0]["error"]["code"] == -32602

    def test_query_tool(self, tmp_path):
        store = TraceStore(str(tmp_path))
        for ok in (True, False):
            rec = Recorder("beta work", save=False)
            rec.trace.success = ok
            store.save(rec.trace)
        params = {"name": "query",
                  "arguments": {"expression": "success == false",
                                "store": str(tmp_path)}}
        raw, _ = _serve([_rpc("tools/call", params)], ServerContext("."))
        payload = json.loads(
            _response_lines(raw)[0]["result"]["content"][0]["text"])
        assert payload["count"] >= 1


class TestHandleRequest:
    def test_non_dict_raises_valueerror(self):
        with pytest.raises(ValueError):
            handle_request(["not", "a", "dict"], ServerContext("."))

    def test_request_without_id_is_notification(self):
        msg = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        assert handle_request(msg, ServerContext(".")) is None
