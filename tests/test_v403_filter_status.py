"""v403: the status filter reads the status, not the prose.

parse_plan excluded any entry whose whole body mentioned
"deferred" or "queued" — written to skip items marked
"(deferred)" or "(queued)", it also swallowed DELIVERED items
that talk about queues: an entry about a ship spool ("a queued
shipment names its own next step") or an awaiting-evidence
note vanished from the changelog while its neighbors shipped.
Twice this bit the ledger (v3.95.0, v4.0.2 both needed
rewording to surface). The filter reads the item's own status
line now — the parenthetical right after the title — and a
body that TALKS about queued work is delivered work about a
queue.
"""

from pathlib import Path

from approximately.changelog import parse_plan


def _plan(tmp_path, body):
    p = tmp_path / "PLAN.md"
    p.write_text("# Plan\n\n" + body, encoding="utf-8")
    return parse_plan(p)


def test_a_body_that_talks_about_queues_still_ships(tmp_path):
    entries = _plan(tmp_path, """1. **v4.0.9 - the spool speaks**
       (planned):
       - A queued shipment names its own next step, and the
         deferred evidence still counts as waiting.""")
    assert [e[0] for e in entries] == ["v4.0.9"], \
        "prose about queues is delivered work about a queue"


def test_a_marked_deferred_entry_is_still_skipped(tmp_path):
    entries = _plan(tmp_path, """1. **v4.0.9 - the slow door**
       (deferred):
       - Not yet; the design is still open.
2. **v4.0.8 - the fast door** (planned):
       - Shipped.""")
    assert [e[0] for e in entries] == ["v4.0.8"], \
        "the marker on the status line still excludes"


def test_a_marked_queued_entry_is_still_skipped(tmp_path):
    entries = _plan(tmp_path, """1. **v4.1.0 - the big door**
       (queued):
       - Waiting for the window.""")
    assert entries == []


def test_status_elsewhere_in_the_body_is_not_a_status(tmp_path):
    entries = _plan(tmp_path, """1. **v4.0.7 - the mixed door**
       (planned):
       - The plan was queued twice in review, then shipped.
         Someone wrote "deferred" in a meeting note pasted
         below.""")
    assert [e[0] for e in entries] == ["v4.0.7"]


def test_the_real_ledger_parses_clean_newest_first():
    entries = parse_plan(Path(__file__).resolve().parent.parent
                         / "docs" / "PLAN.md")
    versions = [e[0] for e in entries]
    assert versions[0] == "v4.0.2"
    # the previously-swallowed entries surface now
    assert "v3.95.0" in versions and "v4.0.2" in versions
