"""Night VI, round 3: the fleet sees the stamp.

A Budget breach recorded by the live rails (v2.70.0) must surface
wherever the fleet is watched: the store summary, the webhook
payload, the alert reasons (with ``--alert-budget-breaches``), the
cooldown dedup, and the HTML store card.  One predicate
(``fleet._budget_breaches``) feeds every surface — including the ci
gate's ``--max-budget-breaches`` ceiling.
"""

import argparse

from approximately.budget import Budget
from approximately.fleet import (
    StoreSummary,
    _alert_reasons,
    _budget_breaches,
    _should_alert,
    _store_card,
    survey,
    watch_fleet,
    webhook_payload,
)
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed(store_dir, breaches=1, clean=2):
    store = TraceStore(store_dir)
    for i in range(clean):
        with Recorder(f"calm {i}", model="m/1", store=store) as rec:
            rec.tool("t", tokens=10)
            rec.respond("done", success=True)
    for i in range(breaches):
        budget = Budget(tokens=5, on_exceed="stamp")
        with Recorder(f"burn {i}", model="m/1", store=store,
                      budget=budget) as rec:
            rec.tool("t", tokens=500)
            rec.respond("burned", success=True)


def _summary(store_dir):
    return survey([store_dir])[0]


def test_predicate_counts_only_stamped_breaches(tmp_path):
    _seed(tmp_path, breaches=2, clean=3)
    store = TraceStore(tmp_path)
    assert _budget_breaches(store.list_traces()) == 2


def test_summary_carries_breach_count(tmp_path):
    _seed(tmp_path, breaches=1)
    assert _summary(tmp_path).budget_breaches == 1
    # a store with no rails never shows a breach
    other = tmp_path.parent / (tmp_path.name + "-clean")
    other.mkdir()
    _seed(other, breaches=0, clean=1)
    assert _summary(other).budget_breaches == 0


def test_webhook_payload_carries_the_field(tmp_path):
    _seed(tmp_path, breaches=1)
    payload = webhook_payload([_summary(tmp_path)])
    assert payload["stores"][0]["budget_breaches"] == 1


def test_should_alert_on_breach_threshold(tmp_path):
    burned = StoreSummary(name="a", path="/a", budget_breaches=2)
    calm = StoreSummary(name="b", path="/b")
    assert _should_alert([burned], None, None, None, None, 1) is True
    assert _should_alert([burned], None, None, None, None, 3) is False
    assert _should_alert([calm], None, None, None, None, 1) is False
    # no thresholds at all: every cycle posts (unchanged default)
    assert _should_alert([calm], None, None, None, None, None) is True
    # a failure threshold alone never fires on a healthy rate
    # (previously `failure_rate >= (None or 0.0)` was always true —
    # any anomaly threshold silently paged on healthy stores too)
    calmish = StoreSummary(name="c", path="/c", token_anomalies=0)
    assert _should_alert([calmish], None, None, 5, None, None) is False


def test_alert_reason_names_the_store_and_kind():
    burned = StoreSummary(name="prod-a", path="/a", budget_breaches=1)
    reasons = _alert_reasons([burned], None, None, None, None, 1)
    assert "prod-a:budget-breaches" in reasons
    calm = StoreSummary(name="prod-b", path="/b")
    assert _alert_reasons([calm], None, None, None, None, 1) \
        == frozenset()


def test_watch_pages_on_breach_and_cooldown_dedups(tmp_path, monkeypatch):
    import json
    from pathlib import Path as P

    _seed(tmp_path, breaches=1)
    digest = tmp_path / "digest"
    pages = []

    def fake_clock():
        fake_clock.t = getattr(fake_clock, "t", 0.0) + 60.0
        return fake_clock.t

    # page only on >=1 breach, cooldown 5 minutes
    written = watch_fleet(
        [tmp_path], P(digest), interval=0.0, iterations=3,
        sleep=lambda s: None, webhook_url="http://hook",
        notify=lambda summaries, url: pages.append(summaries),
        alert_budget_breaches=1, alert_cooldown=300.0, clock=fake_clock)
    assert written == 3
    assert len(pages) == 1  # same alarm ringing: no re-page
    assert pages[0][0].budget_breaches == 1
    # the digest line carries the field too
    lines = sorted(digest.glob("*.jsonl"))
    assert any("budget_breaches" in json.dumps(
        [json.loads(line) for line in f.read_text().splitlines()])
        for f in lines)


def test_watch_repages_when_cooldown_lapses(tmp_path):
    from pathlib import Path as P

    store_dir = tmp_path / "s"
    _seed(store_dir, breaches=1)
    digest = tmp_path / "digest"
    pages = []

    # a 10-minute cooldown, cycles ~7 minutes apart: cycle 1 pages
    # (first page), cycle 2 is the SAME alarm mid-cooldown (no
    # page — a grown COUNT inside one store is not a new reason),
    # cycle 3 lapses and pages again
    ticks = {"t": 0.0}

    def clock():
        ticks["t"] += 400.0
        return ticks["t"]

    watch_fleet([store_dir], P(digest), interval=0.0, iterations=3,
                sleep=lambda s: None, webhook_url="http://hook",
                notify=lambda summaries, url:
                    pages.append(summaries[0].budget_breaches),
                alert_budget_breaches=1, alert_cooldown=600.0,
                clock=clock)
    assert pages == [1, 1]


def test_store_card_renders_the_breach_row(tmp_path):
    _seed(tmp_path, breaches=2)
    html = _store_card(_summary(tmp_path))
    assert "budget breach(es)" in html
    assert '<span class="rate bad">2</span>' in html
    other = tmp_path.parent / (tmp_path.name + "-clean2")
    other.mkdir()
    _seed(other, breaches=0)
    assert "budget breach" not in _store_card(_summary(other))


def test_ci_gate_shares_the_predicate(tmp_path):
    from approximately.cli import cmd_ci
    _seed(tmp_path, breaches=1)
    args = argparse.Namespace(store=str(tmp_path), format=None,
                              json=False, prices=None,
                              min_traces=None, since=None,
                              max_budget_breaches=0)
    assert cmd_ci(args) == 1
