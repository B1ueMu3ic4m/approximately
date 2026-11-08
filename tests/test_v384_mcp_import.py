"""v384: the receiving half is agent-reachable too.

`inbox-import` was shell-only; the `inbox_import` tool reads
the same plan through the same helpers, and its apply carries
the retention two-flag gate — importing is a store mutation,
and store mutations do not ride on one flag. Verified rows
only unless allow_unverified, malformed records never reach
the apply loop, and the chain stays the sender's (stamp=False).
52 tools.
"""

import json
import tempfile

import pytest

from approximately.mcp_server import ServerContext, _tool_inbox_import
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _receiver_store_with_shipments():
    receiver = TraceStore(tempfile.mkdtemp())
    archive = receiver.directory / "webhook-log.jsonl"
    rows = []
    for i in range(2):
        box = TraceStore(tempfile.mkdtemp())
        rec = Recorder(f"shipped task {i}", store=box)
        rec.tool("sh", {"cmd": f"run {i}"}, result="ok")
        rec.respond("done", success=True)
        box.save(rec.trace)
        rows.append({"received_at": 1.0 + i, "verified": True,
                     "kind": "trace_ship",
                     "payload": {"trace": rec.trace.to_dict()}})
    rows.append({"received_at": 9.0, "verified": False,
                 "kind": "trace_ship",
                 "payload": {"trace": {"id": "open1",
                                       "task": "from the open tap",
                                       "steps": []}}})
    with archive.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    return receiver


def _plan(receiver, **kw):
    ctx = ServerContext(receiver.directory)
    return _tool_inbox_import(ctx, dict(kw))


def test_the_plan_is_the_default():
    receiver = _receiver_store_with_shipments()
    plan = _plan(receiver)
    assert plan["found"] == 3
    assert plan["importable"] == 2
    assert plan["unverified_skipped"] == 1
    assert plan["malformed"] == 0
    assert len(TraceStore(receiver.directory).list_traces()) == 0, \
        "a plan imports nothing"


def test_apply_without_confirm_is_refused():
    receiver = _receiver_store_with_shipments()
    with pytest.raises(ValueError, match="needs confirm: true"):
        _plan(receiver, apply=True)


def test_apply_and_confirm_closes_the_arc():
    receiver = _receiver_store_with_shipments()
    result = _plan(receiver, apply=True, confirm=True)
    assert len(result["applied"]) == 2
    traces = TraceStore(receiver.directory).list_traces()
    assert sorted(t.task for t in traces) == \
        ["shipped task 0", "shipped task 1"], \
        "the open tap's row never arrived"


def test_already_present_ids_never_re_import():
    receiver = _receiver_store_with_shipments()
    _plan(receiver, apply=True, confirm=True)
    again = _plan(receiver)
    assert again["already_present"] == 2
    assert again["importable"] == 0, \
        "the second plan finds nothing to do"


def test_allow_unverified_imports_loudly():
    receiver = _receiver_store_with_shipments()
    result = _plan(receiver, apply=True, confirm=True,
                   allow_unverified=True)
    assert len(result["applied"]) == 3
    traces = TraceStore(receiver.directory).list_traces()
    assert any(t.id == "open1" for t in traces), \
        "the override is the operator's, and it works"
