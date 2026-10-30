"""v348: the fleet page reads the inbox too.

The fleet digest's per-store briefs already compute the webhook
inbox; the render just never showed it. Each store's section now
carries one line - the window's rows and verified split - only
when that store keeps an archive.
"""

import json
import tempfile

from approximately.digest import build_fleet_digest, render_fleet_markdown
from approximately.store import TraceStore


def _store(with_archive: bool):
    store = TraceStore(tempfile.mkdtemp())
    if with_archive:
        archive = store.directory / "webhook-log.jsonl"
        import datetime as dt
        start = dt.datetime.combine(dt.date.today(),
                                    dt.time.min).timestamp()
        rows = [{"received_at": start + 60.0 + i,
                 "verified": i == 0, "kind": "spool",
                 "payload": {}} for i in range(3)]
        with archive.open("a", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row) + "\n")
    return store


def test_fleet_page_shows_inbox_only_where_it_exists():
    busy = _store(with_archive=True)
    quiet = _store(with_archive=False)
    page = render_fleet_markdown(
        build_fleet_digest([busy, quiet]))
    assert page.count("webhook inbox: 3 row(s) in window, "
                      "1 verified") == 1, \
        "one line, only for the store with an archive"
    assert "no webhook archive" not in page, \
        "the fleet page stays compact: absent is silent"


def test_absent_inbox_is_silent_but_present_is_counted():
    briefs = build_fleet_digest([_store(with_archive=True)])
    inbox = briefs["stores"][0]["inbox"]
    assert inbox["present"] is True and inbox["rows"] == 3
    assert inbox["verified"] == 1
