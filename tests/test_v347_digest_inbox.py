"""v347: the shift brief reads the inbox.

The webhook channel's archive sat beside the store without ever
reaching the brief. The digest gains an "overnight arrivals
(webhook)" section: the window's rows, the verified split, the
kind census — the same numbers /stats answers, scoped to the
night the brief covers. No archive is one honest line, not an
empty section. The snapshot also learned to carry the archive's
rotated predecessors (`<log>.jsonl.1`) — yesterday's log rides
along with the rest of the evidence.
"""

import json
import tempfile

from approximately.digest import build_digest, render_markdown
from approximately.snapshot import _member_candidates
from approximately.store import TraceStore


def _store_with_archive(rows):
    store = TraceStore(tempfile.mkdtemp())
    archive = store.directory / "webhook-log.jsonl"
    with archive.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    return store


def _window_start():
    import datetime as dt
    midnight = dt.datetime.combine(dt.date.today(), dt.time.min)
    return midnight.timestamp()


def _row(age_days, kind="trace_failure", verified=True):
    # anchored to the window's own start: real-clock ages go stale
    # at midnight (a row 2h ago is yesterday when the clock says
    # 00:10, and the window is today)
    return {"received_at": _window_start() + age_days * 86400.0
            * (1 if age_days >= 0 else 0) + (age_days * 3600.0
                                             if age_days < 1 else 0),
            "verified": verified, "kind": kind, "payload": {}}


def test_inbox_counts_the_window_not_the_history():
    start = _window_start()
    rows = [{"received_at": start + 60.0, "verified": True,
             "kind": "trace_failure", "payload": {}},
            {"received_at": start + 120.0, "verified": True,
             "kind": "ops_digest", "payload": {}},
            {"received_at": start - 60.0, "verified": False,
             "kind": "spool", "payload": {}},
            {"received_at": start - 30 * 86400.0, "verified": True,
             "kind": "old", "payload": {}}]
    store = _store_with_archive(rows)
    payload = build_digest(store)
    inbox = payload["inbox"]
    assert inbox["present"] is True
    assert inbox["rows"] == 2, "only the window's rows count"
    assert inbox["verified"] == 2
    assert inbox["kinds"] == {"trace_failure": 1,
                              "ops_digest": 1}


def test_no_archive_is_one_honest_line():
    store = TraceStore(tempfile.mkdtemp())
    payload = build_digest(store)
    assert payload["inbox"]["present"] is False
    page = render_markdown(payload)
    assert "no webhook archive in this store" in page


def test_render_shows_split_and_kinds():
    start = _window_start()
    rows = [{"received_at": start + 60.0, "verified": True,
             "kind": "trace_failure", "payload": {}},
            {"received_at": start + 120.0, "verified": False,
             "kind": "spool", "payload": {}},
            {"received_at": start + 180.0, "verified": False,
             "kind": "spool", "payload": {}}]
    store = _store_with_archive(rows)
    page = render_markdown(build_digest(store))
    assert "## overnight arrivals (webhook)" in page
    assert "3 row(s) in the window: 1 verified, 2 unverified" in page
    assert "kinds: spool x2, trace_failure x1" in page


def test_snapshot_carries_the_rotated_log():
    store = TraceStore(tempfile.mkdtemp())
    (store.directory / "webhook-log.jsonl").write_text(
        "{}\n", encoding="utf-8")
    (store.directory / "webhook-log.jsonl.1").write_text(
        "{}\n", encoding="utf-8")
    names = {p.name for p in _member_candidates(store.directory)}
    assert "webhook-log.jsonl" in names
    assert "webhook-log.jsonl.1" in names, \
        "yesterday's log rides along with the evidence"
