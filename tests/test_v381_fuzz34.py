"""Fuzz 34: the import door meets hostile shipments.

``inbox-import --apply`` used to trust every trace_ship record
far enough to parse it inside the apply loop — a hostile (or
merely corrupt) archived row crashed the door with a traceback
(``steps: "not a list"`` was enough). The fuzz contract: parse
at PLAN time, mark what will not parse, refuse it by name — the
apply loop never sees a record the plan did not vouch for, and
no raise escapes the door. An open tap's garbage is a finding,
not a crash.
"""

import argparse
import json
import tempfile

from approximately.cli import cmd_inbox_import
from approximately.store import TraceStore

ROWS = [
    {"received_at": 1.0, "verified": True, "kind": "trace_ship",
     "payload": {"trace": {"id": "ok1", "task": "fine",
                           "steps": []}}},
    {"received_at": 2.0, "verified": True, "kind": "trace_ship",
     "payload": {"trace": {"id": "bad1", "task": "lies",
                           "steps": "not a list"}}},
    {"received_at": 3.0, "verified": True, "kind": "trace_ship",
     "payload": {"trace": {"id": "bad2", "task": "worse",
                           "steps": [{"nonsense": True}]}}},
    {"received_at": 4.0, "verified": True, "kind": "trace_ship",
     "payload": {"trace": "a string, not a record"}},
    {"received_at": 5.0, "verified": True, "kind": "trace_ship",
     "payload": {"not": "a shipment"}},
    {"received_at": 6.0, "verified": True, "kind": "trace_ship",
     "payload": {"trace": {"task": "no id at all",
                           "steps": []}}},
]


def _receiver_with(rows):
    receiver = TraceStore(tempfile.mkdtemp())
    archive = receiver.directory / "webhook-log.jsonl"
    with archive.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    return receiver


def _args(receiver, **kw):
    base = {"trace": None, "url": None, "key_file": None,
            "store": str(receiver.directory), "archive": None,
            "apply": False, "allow_unverified": False,
            "include_rotated": False, "json": False}
    base.update(kw)
    return argparse.Namespace(**base)


def test_hostile_shipments_never_crash_the_plan():
    receiver = _receiver_with(ROWS)
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert cmd_inbox_import(_args(receiver)) == 0
    plan = buf.getvalue()
    assert "ok1  fine  [importable]" in plan and \
        "[malformed]" in plan, \
        "the parseable shipment shows, the poison is named"
    assert "bad1" in plan and "bad2" in plan
    assert "a string, not a record" not in plan and \
        "no id at all" not in plan, \
        "rows that are not shipments are not in the plan"


def test_apply_imports_only_what_the_plan_vouched_for(capsys):
    receiver = _receiver_with(ROWS)
    assert cmd_inbox_import(_args(receiver, apply=True)) == 0
    out = capsys.readouterr().out
    assert "imported 1 trace(s)" in out
    assert "ok1" in out
    traces = TraceStore(str(receiver.directory)).list_traces()
    assert [t.id for t in traces] == ["ok1"], \
        "the poison never reached the store"


def test_the_json_plan_counts_malformed():
    receiver = _receiver_with(ROWS)
    args = _args(receiver, json=True)
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert cmd_inbox_import(args) == 0
    plan = json.loads(buf.getvalue())
    assert plan["found"] == 3
    assert plan["importable"] == 1
    assert plan["malformed"] == 2, \
        "bad1 and bad2 refuse; non-records never got here"
    marks = {t["id"]: t.get("malformed") for t in plan["traces"]}
    assert marks["ok1"] is False
    assert marks["bad1"] is True and marks["bad2"] is True


def test_no_id_rows_are_not_shipments():
    receiver = _receiver_with(ROWS)
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert cmd_inbox_import(_args(receiver)) == 0
    assert "no id at all" not in buf.getvalue(), \
        "a record without an id is not a shipment at all"
