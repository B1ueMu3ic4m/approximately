"""Night VI, round 14: the breach count learns to trend.

Digest day-rows already carried each store's budget_breaches (v2.72);
the trend section now reads them like every other series — a
breach_trend verdict (Theil-Sen over the daily counts), a sparkline,
and a day-table column — so "is the fleet burning more or less over
time?" is a glance, not a grep.
"""

import json

from approximately.budget import Budget
from approximately.fleet import (
    append_digest,
    summarize_trend,
    trend_days,
)
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _burn(store_dir, agent=None):
    budget = (Budget(per_agent={agent: 10}) if agent
              else Budget(tokens=10))
    with Recorder(f"burn {agent or 'run'}", model="m/1",
                  store=TraceStore(store_dir),
                  budget=budget) as rec:
        rec.tool("t", agent=agent, tokens=500)
        rec.respond("done", success=True)


def test_day_rows_carry_breach_counts(tmp_path):
    store_dir = tmp_path / "s"
    _burn(store_dir)
    digest = tmp_path / "d"
    append_digest(digest, {
        "generated_at": "2026-10-03T00:00:00+00:00",
        "stores": [dict(
            **webhook_shape(store_dir))]},
    )
    days = trend_days(digest)
    assert days[-1]["last"]["stores"][0]["budget_breaches"] == 1


def webhook_shape(store_dir):
    from approximately.fleet import survey, webhook_payload
    return webhook_payload(survey([store_dir]))["stores"][0]


def _day_entry(day, breaches):
    return {"day": day, "snapshots": 1,
            "last": {"stores": [{"budget_breaches": breaches}]}}


def test_summarize_trend_builds_breach_verdict():
    days = [_day_entry("2026-10-01", 1),
            _day_entry("2026-10-02", 3)]
    summary = summarize_trend(days)
    assert summary["breach_trend"] is not None
    assert summary["breach_trend"]["latest"] == 3
    assert summary["breach_trend"]["verdict"] == "worsening"
    assert summary["days"][-1]["budget_breaches"] == 3


def test_flat_zero_breach_history_has_no_verdict():
    days = [_day_entry(f"2026-10-0{d}", 0) for d in range(1, 4)]
    assert summarize_trend(days)["breach_trend"] is None


def test_single_day_history_has_no_verdict():
    assert summarize_trend([_day_entry("2026-10-01", 7)])[
        "breach_trend"] is None


def test_trend_section_renders_the_breach_curve():
    from approximately.fleet import _trend_section
    days = [_day_entry("2026-10-01", 1),
            _day_entry("2026-10-02", 3)]
    html = _trend_section(summarize_trend(days))
    assert "budget breaches:" in html


def test_digest_rows_are_json_clean(tmp_path):
    store_dir = tmp_path / "s"
    _burn(store_dir)
    from approximately.fleet import digest_snapshot, survey
    line = json.dumps(digest_snapshot(survey([store_dir])))
    payload = json.loads(line)
    stores = payload["stores"] if "stores" in payload else \
        payload.get("last", {}).get("stores", [])
    assert any(s.get("budget_breaches") == 1 for s in stores)
