"""v390: already home, but different.

"already_present" was judged by id alone: a second shipment of
one id with DIFFERENT content silently read as "done" — the
plan said nothing, the store kept the first version, and the
operator never learned a second version existed. The plan
compares the shipped record against the stored one now (byte
for byte, sorted JSON): an identical re-ship is still a silent
"present"; a different version of the same id is named a
conflict in the plan, on both surfaces, and the store keeps
the original — the conflict is reported, never auto-resolved.
"""

import argparse
import contextlib
import io
import json
import tempfile

from approximately.cli import cmd_inbox_import
from approximately.mcp_server import ServerContext, _tool_inbox_import
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _recording(store, task, result="ok"):
    rec = Recorder(task, store=store)
    rec.tool("sh", {"cmd": "deploy"}, result=result)
    rec.respond("done", success=True)
    store.save(rec.trace)
    return rec.trace


def _archive_with(store, rows):
    archive = store.directory / "webhook-log.jsonl"
    with archive.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    return archive


def _ship_row(trace_dict, at=1.0):
    return {"received_at": at, "verified": True,
            "kind": "trace_ship", "payload": {"trace": trace_dict}}


def _args(receiver, **kw):
    base = {"trace": None, "url": None, "key_file": None,
            "store": str(receiver.directory), "archive": None,
            "apply": False, "allow_unverified": False,
            "allow_broken_chain": False,
            "include_rotated": False, "json": False}
    base.update(kw)
    return argparse.Namespace(**base)


def _plan_json(receiver):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cmd_inbox_import(_args(receiver, json=True))
    return json.loads(buf.getvalue())


def _receiver_with(identity_ship):
    """Ship the same id twice: once as recorded, once edited."""
    box = TraceStore(tempfile.mkdtemp())
    trace = _recording(box, "the original recording")
    body = trace.to_dict()
    if identity_ship:
        return box, body, body
    edited = json.loads(json.dumps(body))
    edited["steps"][0]["result"] = "a different story"
    return box, body, edited


def _receiver_store_with(first, second):
    """The receiver imported the first shipment yesterday; the
    archive holds both rows (yesterday's and today's)."""
    from approximately.trace import Trace

    receiver = TraceStore(tempfile.mkdtemp())
    receiver.save(Trace.from_dict(first), stamp=False)
    _archive_with(receiver, [_ship_row(first, at=1.0),
                             _ship_row(second, at=2.0)])
    return receiver


def test_an_identical_reship_stays_silent():
    _box, first, second = _receiver_with(identity_ship=True)
    receiver = _receiver_store_with(first, second)
    plan = _plan_json(receiver)
    row = plan["traces"][0]
    assert row["present"] is True and row["conflict"] is False, \
        "the same evidence twice is just 'present'"
    assert plan["conflicts"] == 0


def test_a_different_version_is_named_a_conflict():
    _box, first, second = _receiver_with(identity_ship=False)
    receiver = _receiver_store_with(first, second)
    plan = _plan_json(receiver)
    assert plan["conflicts"] == 1, \
        "the same id carrying a different record is a conflict"
    row = plan["traces"][0]
    assert row["present"] is True and row["conflict"] is True


def test_apply_never_overwrites_the_original(capsys):
    _box, first, second = _receiver_with(identity_ship=False)
    receiver = _receiver_store_with(first, second)
    assert cmd_inbox_import(_args(receiver, apply=True)) == 0
    out = capsys.readouterr().out
    store = TraceStore(receiver.directory)
    stored = [t for t in store.list_traces()
              if t.id == first["id"]]
    assert len(stored) == 1
    assert stored[0].steps[0].result == "ok", \
        "the store keeps the original; the conflict is reported"
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cmd_inbox_import(_args(receiver))
    assert "conflict: same id, different evidence" in buf.getvalue()


def test_the_mcp_plan_carries_the_conflict():
    _box, first, second = _receiver_with(identity_ship=False)
    receiver = _receiver_store_with(first, second)
    ctx = ServerContext(receiver.directory)
    plan = _tool_inbox_import(ctx, {})
    assert plan["conflicts"] == 1
    assert plan["traces"][0]["conflict"] is True
