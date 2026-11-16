"""v571: the MCP recall surface meets the fleet.

v5.7.0 gave the CLI doors a fleet view (``recall STORE...``); the
MCP tool kept its single-store surface — an MCP client asking
"what was said across all the boxes" had no door. The recall tool
gains ``stores``: a list of store directories read as ONE memory
(the same dedupe, the same per-entry store tag), the summary and
search carrying it too. The wire stays honest: a non-list or
non-string item is refused by name, a typo'd store is "store not
found" — never a silently-created empty store reading as lost
memory — and the schema describes the new key so clients can
discover it.
"""

import json

from approximately.mcp_server import _TOOLS, ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _convo(tmp_path, name, task, *, created=None):
    store = TraceStore(tmp_path / name)
    rec = Recorder(task, model="m/1", store=store, save=False)
    rec.tool("deploy", {"env": name}, result="ok")
    rec.respond("done", success=True)
    if created is not None:
        rec.trace.created_at = created
    store.save(rec.trace)
    return store


def _call(ctx, **arguments):
    payload = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "recall", "arguments": arguments},
    }, ctx)
    return payload


def _result(ctx, **arguments):
    payload = _call(ctx, **arguments)
    return json.loads(payload["result"]["content"][0]["text"])


def _entries(payload):
    return [entry for day in payload["days"]
            for entry in day["entries"]]


def test_the_schema_describes_stores():
    recall = next(t for t in _TOOLS if t["name"] == "recall")
    props = recall["inputSchema"]["properties"]
    assert "stores" in props, \
        "a client cannot discover a door the schema hides"
    assert props["stores"]["items"]["type"] == "string"


def test_the_timeline_interleaves_and_names_stores(tmp_path):
    _convo(tmp_path, "a", "ship the web service", created=1.0)
    _convo(tmp_path, "b", "debug the cron job", created=2.0)
    ctx = ServerContext(str(tmp_path / "a"))
    payload = _result(ctx, stores=[str(tmp_path / "a"),
                                   str(tmp_path / "b")])
    entries = _entries(payload)
    assert [e["task"] for e in entries] == ["ship the web service",
                                            "debug the cron job"]
    assert entries[0]["store"] == "a" and entries[1]["store"] == "b"


def test_a_trace_in_two_boxes_is_one_memory(tmp_path):
    _convo(tmp_path, "a", "ship it")
    b = _convo(tmp_path, "b", "ship it")
    trace = TraceStore(tmp_path / "a").list_traces()[0]
    trace.id = b.list_traces()[0].id
    b.save(trace)
    ctx = ServerContext(str(tmp_path / "a"))
    payload = _result(ctx, stores=[str(tmp_path / "a"),
                                   str(tmp_path / "b")])
    assert len(_entries(payload)) == 2, \
        "the duplicated id counts once (first store wins)"


def test_the_summary_and_search_carry_the_fleet(tmp_path):
    _convo(tmp_path, "a", "ship the web service")
    _convo(tmp_path, "b", "debug the cron job")
    ctx = ServerContext(str(tmp_path / "a"))
    summary = _result(ctx, stores=[str(tmp_path / "a"),
                                   str(tmp_path / "b")],
                      summarize=True)
    assert sorted(summary["days"][-1]["stores"]) == ["a", "b"]
    hits = _result(ctx, stores=[str(tmp_path / "a"),
                                str(tmp_path / "b")],
                   grep="cron")
    assert hits["hits"] == 1
    assert hits["results"][0]["store"] == "b"


def test_hostile_stores_answer_by_name(tmp_path):
    _convo(tmp_path, "a", "ship it")
    ctx = ServerContext(str(tmp_path / "a"))
    for bad in ({"stores": "not-a-list"}, {"stores": [1, 2]}):
        payload = _call(ctx, **bad)
        assert payload["result"]["isError"], (
            f"{bad} must be a refusal, not a crash")
        assert "stores must be a list of paths" in \
            payload["result"]["content"][0]["text"]
    payload = _call(ctx, stores=[str(tmp_path / "typo")])
    assert payload["result"]["isError"]
    assert "store not found" in payload["result"]["content"][0]["text"]
    assert not (tmp_path / "typo").exists()


def test_without_stores_the_shape_is_unchanged(tmp_path):
    _convo(tmp_path, "a", "the only one")
    ctx = ServerContext(str(tmp_path / "a"))
    payload = _result(ctx)
    entries = _entries(payload)
    assert len(entries) == 1
    assert "store" not in entries[0], \
        "the single-store wire shape gains no key"
