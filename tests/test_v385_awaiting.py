"""v385: the brief counts the evidence waiting at the door.

The evidence arc shipped twice over (webhook-ship, inbox-import,
both surfaces) but nothing TOLD the operator the middle step was
owed: traces arrived as trace_ship rows and sat in the archive
until someone thought to run inbox-import. The digest brief and
the status frame now count shipments_awaiting — verified rows
whose traces are not in the store yet, a trace counted once no
matter how many rows carried it, the whole archive counted
(awaiting is about now, not about the window) — and name the
next step in the brief's own voice. An already-imported arc is
silent, not a zero parade.
"""

import json
import tempfile

from approximately.digest import build_digest, render_markdown, shipments_awaiting
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _shipped_row(trace_dict, verified=True, at=1.0):
    return {"received_at": at, "verified": verified,
            "kind": "trace_ship", "payload": {"trace": trace_dict}}


def _trace_in(store, task="arriving task"):
    rec = Recorder(task, store=store)
    rec.tool("sh", {"cmd": "x"}, result="ok")
    rec.respond("done", success=True)
    store.save(rec.trace)
    return rec.trace


def _store_with_shipments(rows):
    store = TraceStore(tempfile.mkdtemp())
    archive = store.directory / "webhook-log.jsonl"
    with archive.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    return store, archive


def test_the_helper_counts_unimported_verified_shipments():
    store = TraceStore(tempfile.mkdtemp())
    box = TraceStore(tempfile.mkdtemp())
    t1 = _trace_in(box, "task one")
    t2 = _trace_in(box, "task two")
    t3 = _trace_in(box, "already home")
    store.save(t3, stamp=False)
    _store, archive = _store_with_shipments([
        _shipped_row(t1.to_dict()),
        _shipped_row(t2.to_dict()),
        _shipped_row(t1.to_dict(), at=2.0),  # shipped twice: once
        _shipped_row(t3.to_dict(), at=3.0),  # already imported: no
        _shipped_row(t1.to_dict(), verified=False, at=4.0),
    ])
    assert shipments_awaiting(store, archive) == 2, \
        "dedup by id, present ids stay silent, unverified wait"


def test_the_brief_names_the_next_step():
    box = TraceStore(tempfile.mkdtemp())
    t1 = _trace_in(box, "arriving task")
    _store, _archive = _store_with_shipments(
        [_shipped_row(t1.to_dict())])
    payload = build_digest(_store)
    page = render_markdown(payload)
    assert "shipped evidence awaiting import: 1 trace(s)" in page
    assert "inbox-import will bring them home" in page


def test_an_imported_arc_is_silent_in_the_brief():
    store = TraceStore(tempfile.mkdtemp())
    box = TraceStore(tempfile.mkdtemp())
    t1 = _trace_in(box, "already home")
    store.save(t1, stamp=False)
    archive = store.directory / "webhook-log.jsonl"
    with archive.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(_shipped_row(t1.to_dict()),
                            sort_keys=True) + "\n")
    page = render_markdown(build_digest(store))
    assert "awaiting import" not in page, \
        "no zero parade for work already done"


def test_awaiting_sees_the_rotated_log():
    # shipped at 23:59, rotated at midnight, still waiting at 00:01
    store = TraceStore(tempfile.mkdtemp())
    box = TraceStore(tempfile.mkdtemp())
    t1 = _trace_in(box, "rotated shipment")
    rotated = store.directory / "webhook-log.jsonl.1"
    rotated.write_text(json.dumps(_shipped_row(t1.to_dict()),
                                  sort_keys=True) + "\n",
                       encoding="utf-8")
    current = store.directory / "webhook-log.jsonl"
    current.write_text(json.dumps(_shipped_row(
        {"id": "current1", "task": "current", "steps": []}),
        sort_keys=True) + "\n", encoding="utf-8")
    assert shipments_awaiting(store, current) == 2, \
        "yesterday's shipment still counts as waiting"


def test_the_status_frame_carries_the_count():
    from approximately.cli import _status_payload

    store = TraceStore(tempfile.mkdtemp())
    box = TraceStore(tempfile.mkdtemp())
    t1 = _trace_in(box, "arriving task")
    archive = store.directory / "webhook-log.jsonl"
    with archive.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(_shipped_row(t1.to_dict()),
                            sort_keys=True) + "\n")
    payload = _status_payload(store, store.list_traces(), None)
    assert payload["webhook_inbox"]["shipments_awaiting"] == 1
    frame = _frame_text(payload)
    assert "awaiting import: 1 trace(s)" in frame


def _frame_text(payload):
    import io

    from approximately.cli import _write_inbox_lines

    buf = io.StringIO()
    _write_inbox_lines(buf, payload.get("webhook_inbox") or {})
    return buf.getvalue()


def test_the_frame_stays_silent_when_nothing_waits():
    from approximately.cli import _status_payload

    store = TraceStore(tempfile.mkdtemp())
    payload = _status_payload(store, store.list_traces(), None)
    assert payload["webhook_inbox"]["shipments_awaiting"] == 0
    assert "awaiting import" not in _frame_text(payload)
