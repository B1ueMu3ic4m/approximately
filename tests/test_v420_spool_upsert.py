"""v420: the spool dedupes — one (trace_id, url), one row.

A cron that re-spools a failing shipment nightly grew the queue
by one duplicate a day: five nights of failures left five rows
for the same trace, the flush re-posted it five times per pass,
and the ops counts lied about how much work was actually
waiting. An append for a key already queued is a refresh now —
the row moves to the back of the queue with a fresh stamp, its
accumulated ``attempts`` survive (honest retry history), and
the queue stays one-entry-per-shipment.
"""

import tempfile
import time

from approximately import cli
from approximately.cli import _spool_append, _spool_rewrite, _spool_rows
from approximately.recorder import Recorder
from approximately.store import TraceStore


def test_respooling_the_same_shipment_refreshes_not_duplicates():
    spool = _spool()
    _spool_append(spool, "t1", "http://127.0.0.1:1/", "box-a")
    rows = _spool_rows(spool)
    rows[0]["attempts"] = 3  # a flush's honest failure count
    _spool_rewrite(spool, rows)
    time.sleep(1.1)
    _spool_append(spool, "t1", "http://127.0.0.1:1/", "box-a")
    rows = _spool_rows(spool)
    assert len(rows) == 1, \
        "the second night does not grow the queue"
    assert rows[0]["attempts"] == 3, \
        "the refresh keeps the accumulated attempts"
    assert rows[0]["queued_at"] > 1_700_000_000, \
        "the row moved to the back with a fresh stamp"


def test_a_different_url_or_trace_is_a_new_row():
    spool = _spool()
    _spool_append(spool, "t1", "http://127.0.0.1:1/", "box-a")
    _spool_append(spool, "t1", "http://127.0.0.1:2/", "box-a")
    _spool_append(spool, "t2", "http://127.0.0.1:1/", "box-a")
    assert len(_spool_rows(spool)) == 3, \
        "dedupe keys on (trace_id, url), nothing else"


def test_the_refresh_updates_the_sender_label():
    spool = _spool()
    _spool_append(spool, "t1", "http://127.0.0.1:1/", "box-a")
    _spool_append(spool, "t1", "http://127.0.0.1:1/", "box-b")
    rows = _spool_rows(spool)
    assert len(rows) == 1
    assert rows[0]["sender"] == "box-b", \
        "the newest label is the honest one"


def test_a_failing_cron_night_stays_one_row():
    store = TraceStore(tempfile.mkdtemp())
    rec = Recorder("cron doomed", store=store)
    rec.tool("sh", {"cmd": "x"}, result="ok")
    rec.respond("gave up", success=False)
    store.save(rec.trace)
    spool = cli._spool_path(str(store.directory))
    for _night in range(5):
        _spool_append(spool, rec.trace.id,
                      "http://127.0.0.1:1/", "box-a")
    assert len(_spool_rows(spool)) == 1, \
        "five nights of re-spools leave one shipment, not five"
    from approximately.digest import spool_waiting

    assert spool_waiting(store) == 1, \
        "the ops counts tell the truth about the work waiting"


def _spool():
    import tempfile
    from pathlib import Path

    return Path(tempfile.mkdtemp()) / "ship-spool.jsonl"
