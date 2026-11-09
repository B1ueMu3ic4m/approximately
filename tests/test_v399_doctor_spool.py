"""v399: the nightly pass sees the outbox.

doctor walked the store's records, ledger, locks and the
receiver's archive — but the SHIP spool (--spool's queue of
refused shipments) was invisible to it: a queue could sit owed
for days while every nightly pass said "healthy", and unreadable
lines in it were nobody's finding until a flush happened to
drop them. doctor counts the spool now: waiting is not
unhealthy (it is owed — the report names the flush), unreadable
lines are counted and named. The outbox is part of the box's
health because the outbox is part of the box's promises.
"""

import argparse
import json
import tempfile

from approximately.cli import cmd_doctor
from approximately.doctor import doctor
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store_with_spool(rows_text=None, shipments=0):
    store = TraceStore(tempfile.mkdtemp())
    rec = Recorder("doctor spool task", store=store)
    rec.tool("sh", {"cmd": "x"}, result="ok")
    rec.respond("done", success=True)
    store.save(rec.trace)
    if rows_text is None and shipments:
        rows_text = "".join(
            json.dumps({"queued_at": 1.0,
                        "trace_id": f"t{i}",
                        "url": "http://127.0.0.1:1/",
                        "sender": "box-a",
                        "attempts": 0}, sort_keys=True) + "\n"
            for i in range(shipments))
    if rows_text is not None:
        (store.directory / "ship-spool.jsonl").write_text(
            rows_text, encoding="utf-8")
    return store


def test_doctor_counts_the_waiting_shipments():
    store = _store_with_spool(shipments=2)
    report = doctor(store.directory)
    assert report.ship_spool_waiting == 2
    assert report.ship_spool_unreadable == 0
    assert report.healthy, "owed is not unhealthy"
    page = report.render()
    assert "ship spool: 2 shipment(s) waiting" in page
    assert "webhook-ship --flush retries them" in page


def test_unreadable_lines_are_counted_not_fatal():
    store = _store_with_spool(rows_text=(
        '{"trace_id": "kept", "url": "http://x", '
        '"queued_at": 1, "attempts": 0}\n'
        'not json at all\n'))
    report = doctor(store.directory)
    assert report.ship_spool_waiting == 1
    assert report.ship_spool_unreadable == 1
    assert report.healthy, \
        "the flush drops them loudly; doctor names them"
    assert "1 unreadable line(s)" in report.render()


def test_no_spool_is_one_honest_silence():
    store = _store_with_spool(rows_text=None)
    report = doctor(store.directory)
    assert report.ship_spool_waiting == 0
    assert "ship spool" not in report.render(), \
        "no zero parade for a queue that does not exist"


def test_the_json_report_carries_the_counts():
    import contextlib
    import io

    store = _store_with_spool(shipments=1)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cmd_doctor(argparse.Namespace(
            store=str(store.directory), digest_dir=None,
            judge_cache=None, spool=None, deep=False,
            fix=False, json=True))
    assert code == 0
    out = json.loads(buf.getvalue())
    assert out["ship_spool_waiting"] == 1
    assert out["ship_spool_unreadable"] == 0
