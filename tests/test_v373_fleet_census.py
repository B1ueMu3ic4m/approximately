"""v373: the fleet card answers the same census.

After v372 closed the MCP and status-frame parity holes, one
surface still dropped the kind census: the fleet dashboard's
store cards said "webhook inbox: 3 row(s), 2 verified" and
stopped. The survey's JSON payload dropped it too. One reader,
one answer set — the card and the payload now carry the census
in the digest's exact format, and a store without an archive
answers the same shape it always did.
"""

import json
import tempfile

from approximately.fleet import StoreSummary, render_fleet_html, survey
from approximately.store import TraceStore


def _store_with_archive(kinds=("trace_failure", "spool")):
    store = TraceStore(tempfile.mkdtemp())
    archive = store.directory / "webhook-log.jsonl"
    rows = [{"received_at": 1.0 + i, "verified": i % 2 == 0,
             "kind": kinds[i % len(kinds)], "payload": {}}
            for i in range(4)]
    with archive.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    return store


def test_survey_carries_the_census():
    store = _store_with_archive()
    summaries = survey([store.directory])
    kinds = getattr(summaries[0], "inbox_kinds", None)
    assert kinds == {"spool": 2, "trace_failure": 2}, \
        "the survey answers the census /stats answers"


def test_survey_payload_carries_the_census():
    store = _store_with_archive()
    summaries = survey([store.directory])
    from approximately.fleet import webhook_payload
    payload = webhook_payload(summaries)
    card = next(c for c in payload["stores"]
                if c.get("inbox_rows"))
    assert card["inbox_kinds"] == {"spool": 2,
                                   "trace_failure": 2}


def test_the_card_renders_the_census_like_the_digest():
    store = _store_with_archive()
    summaries = survey([store.directory])
    page = render_fleet_html(summaries)
    assert "(spool x2, trace_failure x2)" in page, \
        "the digest's exact census format, on the card"


def test_a_store_without_archive_keeps_the_old_shape():
    store = TraceStore(tempfile.mkdtemp())
    summaries = survey([store.directory])
    s = summaries[0]
    assert s.inbox_rows == 0 and s.inbox_kinds == {}
    page = render_fleet_html(summaries)
    assert "webhook inbox" not in page


def test_a_legacy_summary_still_renders():
    # a StoreSummary built before v373 has no inbox_kinds at all
    legacy = StoreSummary(name="old", path="/tmp/old", traces=1,
                          failed=0, inbox_rows=3, inbox_verified=1)
    page = render_fleet_html([legacy])
    assert "webhook inbox: 3 row(s), 1 verified" in page
    assert "spool" not in page, "no census appears out of nowhere"
