"""v389: the plan reads the chain.

inbox-import validated that a shipment PARSES — never that its
evidence holds together. A trace whose own integrity chain does
not verify (steps edited after signing) sailed through as
importable: the receiving box filed a record that claims
integrity it does not have, stamped by nobody, next to real
evidence. The plan verifies each shipment's foreign chain at
plan time now — intact ships, unsigned ships (a hand-made
record makes no claim), keyed and wrong-key stay locked-not-
broken — and a TAMPERED chain is named in the plan and refused
at the apply: evidence that claims integrity it does not have
is not evidence. The override is explicit and loud
(--allow-broken-chain / allow_broken_chain), and the plan
carries the verdict as data either way.
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


def _recording(store, task="honest recording"):
    rec = Recorder(task, store=store)
    rec.tool("sh", {"cmd": "deploy"}, result="ok")
    rec.respond("done", success=True)
    store.save(rec.trace)
    return rec.trace


def _archive_with(store, rows):
    archive = store.directory / "webhook-log.jsonl"
    with archive.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    return archive


def _ship_row(trace_dict, verified=True, at=1.0):
    return {"received_at": at, "verified": verified,
            "kind": "trace_ship", "payload": {"trace": trace_dict}}


def _receiver_with_tampered():
    """One intact shipped trace and one edited after signing."""
    box = TraceStore(tempfile.mkdtemp())
    honest = _recording(box, "honest recording")
    edited = _recording(box, "edited recording")
    body = edited.to_dict()
    body["steps"][0]["result"] = "steps were rewritten in flight"
    receiver = TraceStore(tempfile.mkdtemp())
    _archive_with(receiver, [
        _ship_row(honest.to_dict(), at=1.0),
        _ship_row(body, at=2.0),
    ])
    return receiver


def _args(receiver, **kw):
    base = {"trace": None, "url": None, "key_file": None,
            "store": str(receiver.directory), "archive": None,
            "apply": False, "allow_unverified": False,
            "allow_broken_chain": False,
            "include_rotated": False, "json": False}
    base.update(kw)
    return argparse.Namespace(**base)


def _plan_json(receiver, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cmd_inbox_import(_args(receiver, json=True, **kw))
    return json.loads(buf.getvalue())


def test_the_plan_names_the_broken_chain():
    receiver = _receiver_with_tampered()
    plan = _plan_json(receiver)
    assert plan["found"] == 2
    assert plan["importable"] == 1, \
        "the edited recording is not importable"
    assert plan["chain_broken"] == 1
    marks = {t["id"]: t["chain"] for t in plan["traces"]}
    assert "tampered" in marks.values(), \
        "the verdict is data, not a silent refusal"
    assert "intact" in marks.values()


def test_apply_never_files_tampered_evidence(capsys):
    receiver = _receiver_with_tampered()
    assert cmd_inbox_import(_args(receiver, apply=True)) == 0
    out = capsys.readouterr()
    assert "imported 1 trace(s)" in out.out
    store = TraceStore(receiver.directory)
    tasks = [t.task for t in store.list_traces()]
    assert tasks == ["honest recording"], \
        "the rewritten steps never reached the store"
    assert "tampered chain" in out.err, \
        "the refusal names its override"


def test_the_override_imports_loudly(capsys):
    receiver = _receiver_with_tampered()
    plan = _plan_json(receiver, allow_broken_chain=True)
    assert plan["importable"] == 2
    assert cmd_inbox_import(_args(
        receiver, apply=True, confirm=True,
        allow_broken_chain=True)) == 0
    store = TraceStore(receiver.directory)
    assert len(store.list_traces()) == 2


def test_unsigned_records_import_without_a_claim():
    receiver = TraceStore(tempfile.mkdtemp())
    _archive_with(receiver, [
        _ship_row({"id": "handmade", "task": "no chain",
                   "steps": []}, at=1.0),
    ])
    plan = _plan_json(receiver)
    assert plan["importable"] == 1, \
        "a hand-made record claims no integrity - it ships"
    assert plan["chain_broken"] == 0


def test_the_mcp_plan_carries_the_verdict():
    receiver = _receiver_with_tampered()
    ctx = ServerContext(receiver.directory)
    plan = _tool_inbox_import(ctx, {})
    assert plan["importable"] == 1
    assert plan["chain_broken"] == 1
    result = _tool_inbox_import(
        ctx, {"apply": True, "confirm": True,
              "allow_broken_chain": True})
    assert len(result["applied"]) == 2


def test_the_mcp_gate_needs_confirm():
    receiver = _receiver_with_tampered()
    ctx = ServerContext(receiver.directory)
    import pytest

    with pytest.raises(ValueError, match="needs confirm"):
        _tool_inbox_import(ctx, {"apply": True})
