"""v119: MCP tool #23 regression_test — mint a guard from a failure.

The `test` CLI's promise ("the failure can never silently return")
becomes a tool: an agent that just failed can mint its own
self-contained pytest file, trace riding along as base64, and commit
it where its tests live.
"""

import ast
import json

from approximately.mcp_server import _TOOLS, ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store(tmp_path):
    store = TraceStore(str(tmp_path / "s"))
    rec = Recorder("book the flight", save=False)
    rec.trace.id = "rg-1"
    rec.tool("book", {"seat": "12A"}, result=None, error="timeout")
    rec.respond("gave up", success=False)
    store.save(rec.trace)
    return store


def _call(arguments):
    return handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "regression_test",
                   "arguments": arguments},
    }, ServerContext("."))


def test_registered():
    assert "regression_test" in [t["name"] for t in _TOOLS]


def test_mints_valid_python(tmp_path):
    store = _store(tmp_path)
    resp = _call({"trace": "rg-1", "store": str(store.directory)})
    assert resp["result"]["isError"] is False
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["filename"] == "test_approximately_rg-1.py"
    # the minted file is valid Python and pins this trace id
    ast.parse(payload["content"])
    assert "rg-1" in payload["content"]
    assert "pytest" in payload["content"] or "def test_" in payload["content"]


def test_missing_trace_is_tool_error(tmp_path):
    store = _store(tmp_path)
    resp = _call({"trace": "nope", "store": str(store.directory)})
    assert resp["result"]["isError"] is True


def test_budget_flows_through(tmp_path):
    store = _store(tmp_path)
    resp = _call({"trace": "rg-1", "store": str(store.directory),
                  "budget": 800})
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert "800" in payload["content"]
