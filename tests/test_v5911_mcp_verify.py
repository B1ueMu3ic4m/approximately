"""v5911: the MCP verify surface meets the fleet.

v5.9.10 gave the CLI door a fleet view; the MCP verify tool kept
its single-store surface — an agent harness asking "is EVERY
box's evidence still good?" had no door. The verify tool gains
``stores`` (with all=true): a tally per store, the same shape the
CLI's fleet mode aggregates. The wire stays honest: a non-list
item and a typo'd path answer by name (the recall doors'
convention), the schema describes the key, and the single-store
wire shape gains nothing.
"""

import json

from approximately.mcp_server import _TOOLS, ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _convo(tmp_path, name):
    store = TraceStore(tmp_path / name)
    rec = Recorder(f"fleet {name}", model="m/1", store=store,
                   save=False)
    rec.tool("deploy", {"env": name}, result="ok")
    rec.respond("done", success=True)
    store.save(rec.trace)
    return store


def _call(ctx, arguments):
    """One tool call: (parsed data, isError)."""
    payload = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "verify", "arguments": arguments},
    }, ctx)
    result = payload["result"]
    return (json.loads(result["content"][0]["text"]),
            result.get("isError", False))


def test_the_schema_describes_stores():
    verify = next(t for t in _TOOLS if t["name"] == "verify")
    assert "stores" in verify["inputSchema"]["properties"], \
        "a client cannot discover a door the schema hides"


def test_a_fleet_tally_per_store(tmp_path):
    _convo(tmp_path, "a")
    _convo(tmp_path, "b")
    ctx = ServerContext(str(tmp_path / "a"))
    data, is_error = _call(ctx, {"all": True,
                                 "stores": [str(tmp_path / "a"),
                                            str(tmp_path / "b")]})
    assert is_error is False
    assert data["all"] is True
    assert [s["store"] for s in data["stores"]] == ["a", "b"]
    assert all(s["tally"]["intact"] == 1 for s in data["stores"])


def test_hostile_stores_answer_by_name(tmp_path):
    _convo(tmp_path, "a")
    ctx = ServerContext(str(tmp_path / "a"))
    bad, is_error = _call(ctx, {"all": True,
                                "stores": "not-a-list"})
    assert is_error, "a non-list is a refusal"
    assert "stores must be a list of paths" in json.dumps(bad)
    missing, missing_error = _call(
        ctx, {"all": True, "stores": [str(tmp_path / "typo")]})
    assert missing_error
    assert "store not found" in json.dumps(missing)
    assert not (tmp_path / "typo").exists()


def test_without_stores_the_shape_is_unchanged(tmp_path):
    _convo(tmp_path, "a")
    ctx = ServerContext(str(tmp_path / "a"))
    data, is_error = _call(ctx, {"all": True})
    assert is_error is False
    assert data["all"] is True
    assert data["tally"]["intact"] == 1
    assert "stores" not in data, \
        "the single-store wire shape gains no key"
    single, _err = _call(ctx, {"trace": TraceStore(tmp_path / "a")
                               .list_traces()[0].id})
    assert single.get("trace"), "a per-trace verify still answers"
