"""v395: the brief counts the outbox too.

The brief counted the evidence waiting at the door it opens
ONTO (shipments_awaiting) but not the queue at the door it
opens FROM: --spool queued refused shipments in silence, and
only an operator who remembered the flag would ever run
--flush. The digest brief and the status frame count
ship-spool.jsonl now — a queued shipment names its own next
step ("webhook-ship --flush retries them"), an empty spool is
one honest silence, and a corrupt line counts as nothing (the
spool door already drops it loudly).
"""

import json
import tempfile

from approximately.cli import _status_payload, _write_inbox_lines
from approximately.digest import build_digest, render_markdown, spool_waiting
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _trace_in(store, task="spooled task"):
    rec = Recorder(task, store=store)
    rec.tool("sh", {"cmd": "x"}, result="ok")
    rec.respond("done", success=True)
    store.save(rec.trace)
    return rec.trace


def _spool_rows_for(store, n=1):
    rows = [{"queued_at": 1.0, "trace_id": f"t{i}",
             "url": "http://127.0.0.1:1/", "sender": "box-a",
             "attempts": 0} for i in range(n)]
    spool = store.directory / "ship-spool.jsonl"
    with spool.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    return spool


def test_the_helper_counts_the_outbox():
    store = TraceStore(tempfile.mkdtemp())
    _trace_in(store)
    assert spool_waiting(store) == 0, "no spool, no queue"
    _spool_rows_for(store, 3)
    assert spool_waiting(store) == 3


def test_the_brief_names_the_flush():
    store = TraceStore(tempfile.mkdtemp())
    _trace_in(store)
    _spool_rows_for(store, 1)
    page = render_markdown(build_digest(store))
    assert "ship spool: 1 shipment(s) queued" in page
    assert "webhook-ship --flush retries them" in page


def test_an_empty_spool_is_silent():
    store = TraceStore(tempfile.mkdtemp())
    _trace_in(store)
    page = render_markdown(build_digest(store))
    assert "ship spool" not in page, \
        "no zero parade for a queue that does not exist"


def test_the_frame_carries_the_outbox():
    store = TraceStore(tempfile.mkdtemp())
    _trace_in(store)
    _spool_rows_for(store, 2)
    payload = _status_payload(store, store.list_traces(), None)
    assert payload["webhook_inbox"]["ship_spool"] == 2
    import io

    buf = io.StringIO()
    _write_inbox_lines(buf, payload["webhook_inbox"])
    assert "ship spool: 2 shipment(s) queued" in buf.getvalue()


def test_a_corrupt_line_is_not_a_shipment():
    store = TraceStore(tempfile.mkdtemp())
    _trace_in(store)
    spool = store.directory / "ship-spool.jsonl"
    spool.write_text('{"trace_id": "kept", "url": "http://x",'
                     ' "queued_at": 1, "attempts": 0}\n'
                     'not json at all\n', encoding="utf-8")
    assert spool_waiting(store) == 1, \
        "poison is the spool door's finding, not the brief's count"
