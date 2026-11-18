"""v5914: the MCP handoff surface meets the worklist.

The CLI handoff door grew --queue (v1.6) and then the fleet
worklist (v5.9.13); the MCP handoff tool stayed per-trace — an
agent asking "what failures should I work off?" had to call
triage and handoff separately and stitch the pages itself. The
handoff tool gains queue=N (the postmortem worklist) and
stores=[...] (the fleet worklist, every brief naming its box).
The wire stays honest: queue < 1 refuses by name, a typo'd store
answers by name, the schema describes both keys, and the
per-trace shape is unchanged.
"""

import json

from approximately.mcp_server import ServerContext, _TOOLS, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _failed(tmp_path, name, task):
    store = TraceStore(tmp_path / name)
    rec = Recorder(task, model="m/1", store=store, save=False)
    rec.tool("deploy", {"env": name}, result=None, error="boom")
    rec.respond("done", success=False)
    store.save(rec.trace)
    return store


def _call(ctx, arguments):
    payload = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "handoff", "arguments": arguments},
    }, ctx)
    result = payload["result"]
    return (json.loads(result["content"][0]["text"]),
            result.get("isError", False))


def test_the_schema_describes_queue_and_stores():
    handoff = next(t for t in _TOOLS if t["name"] == "handoff")
    props = handoff["inputSchema"]["properties"]
    assert "queue" in props and "stores" in props, \
        "a client cannot discover a door the schema hides"
    assert "trace" not in handoff["inputSchema"].get("required", []), \
        "the worklist replaces the trace requirement"


def test_the_worklist_answers_over_one_store(tmp_path):
    _failed(tmp_path, "a", "the checkout crash")
    ctx = ServerContext(str(tmp_path / "a"))
    data, is_error = _call(ctx, {"queue": 3})
    assert is_error is False
    assert "postmortem worklist" in data["markdown"]
    assert "the checkout crash" in data["markdown"]
    assert data["queue"] == 3


def test_the_fleet_worklist_names_each_box(tmp_path):
    _failed(tmp_path, "a", "the checkout crash")
    _failed(tmp_path, "b", "the cron hang")
    ctx = ServerContext(str(tmp_path / "a"))
    data, is_error = _call(
        ctx, {"queue": 5, "stores": [str(tmp_path / "a"),
                                     str(tmp_path / "b")]})
    assert is_error is False
    assert "(fleet)" in data["markdown"]
    assert "> store: a" in data["markdown"] and \
        "> store: b" in data["markdown"], \
        "each brief names its box"


def test_hostile_queue_and_stores_answer_by_name(tmp_path):
    _failed(tmp_path, "a", "a crash")
    ctx = ServerContext(str(tmp_path / "a"))
    bad, is_error = _call(ctx, {"queue": 0})
    assert is_error and "queue must be >= 1" in json.dumps(bad)
    missing, missing_error = _call(
        ctx, {"queue": 3, "stores": [str(tmp_path / "typo")]})
    assert missing_error
    assert "store not found" in json.dumps(missing)
    junk, junk_error = _call(ctx, {"queue": 3, "stores": "nope"})
    assert junk_error and "stores must be a list of paths" in \
        json.dumps(junk)


def test_the_per_trace_shape_is_unchanged(tmp_path):
    _failed(tmp_path, "a", "a crash")
    ctx = ServerContext(str(tmp_path / "a"))
    trace_id = TraceStore(tmp_path / "a").list_traces()[0].id
    data, is_error = _call(ctx, {"trace": trace_id})
    assert is_error is False
    assert data["trace"] == trace_id
    assert "queue" not in data, \
        "the per-trace wire shape gains no key"
