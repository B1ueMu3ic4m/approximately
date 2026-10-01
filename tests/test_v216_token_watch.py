"""v216: the night watch notices token burn on its own.

`fleet --watch --alert-tokens N` pages when a store carries N token
burn outliers — the same quiet-by-default contract as the latency
gate — and the trend digest carries a token-burn series with its own
Theil-Sen verdict, so a growing burn problem is visible in the trend
report without anyone rerunning the detectors by hand.
"""

import argparse
import json

from approximately.cli import cmd_fleet
from approximately.fleet import _should_alert, survey, watch_fleet
from approximately.recorder import Recorder
from approximately.store import TraceStore
from approximately.trace import Step, Trace


def _burn_trace(ident="loopy"):
    trace = Trace(task="loopy run", id=ident, created_at=1.0)
    for tokens in (110, 95, 105, 90, 100, 115, 85, 120, 108, 92):
        trace.add(Step(kind="tool_call", tool="search",
                       tokens=tokens, latency_ms=40))
    trace.add(Step(kind="tool_call", tool="search", tokens=9000,
                   latency_ms=40))
    trace.add(Step(kind="response", result="done"))
    return trace


def _store_with_burn(path):
    store = TraceStore(path)
    store.save(_burn_trace())
    return store


def test_alert_tokens_pages_on_burn(tmp_path):
    # same contract as the latency gate (v162): a rate threshold
    # quietens the watch, the anomaly gates add fire conditions
    burn_dir = tmp_path / "burn"
    _store_with_burn(burn_dir)
    summaries = survey([burn_dir])
    assert summaries[0].token_anomalies >= 1
    assert _should_alert(summaries, 0.5, alert_tokens=1) is True
    assert _should_alert(summaries, 0.5, alert_tokens=50) is False


def test_alert_tokens_quiet_on_healthy_fleet(tmp_path):
    calm = tmp_path / "calm"
    store = TraceStore(calm)
    rec = Recorder("calm", save=False)
    rec.respond("done", success=True)
    store.save(rec.trace)
    summaries = survey([calm])
    assert _should_alert(summaries, 0.5, alert_tokens=1) is False


def test_watch_alerts_with_tokens(tmp_path):
    burn_dir = tmp_path / "burn"
    _store_with_burn(burn_dir)
    digest_dir = tmp_path / "digest"
    posts = []
    watch_fleet([burn_dir], digest_dir, interval=0.0, iterations=2,
                webhook_url="http://example.test/hook",
                notify=lambda summaries, url: posts.append(summaries),
                alert_worse_than=0.99, alert_tokens=1)
    assert len(posts) == 2


def test_watch_stays_quiet_without_signal(tmp_path):
    calm_dir = tmp_path / "calm"
    store = TraceStore(calm_dir)
    rec = Recorder("calm", save=False)
    rec.respond("done", success=True)
    store.save(rec.trace)
    digest_dir = tmp_path / "digest"
    posts = []
    watch_fleet([calm_dir], digest_dir, interval=0.0, iterations=2,
                webhook_url="http://example.test/hook",
                notify=lambda summaries, url: posts.append(summaries),
                alert_worse_than=0.99, alert_tokens=1)
    assert posts == []


def test_trend_digest_carries_token_series(tmp_path):
    import time

    from approximately.fleet import append_digest, digest_snapshot, summarize_trend, trend_days

    burn_dir = tmp_path / "burn"
    _store_with_burn(burn_dir)
    summaries = survey([burn_dir])
    digest_dir = tmp_path / "digest"
    for offset in (2, 1):
        snap = digest_snapshot(summaries)
        snap["ts"] = time.time() - offset * 86400
        append_digest(digest_dir, snap)
    summary = summarize_trend(trend_days(digest_dir))
    rows = summary["days"]
    assert all("token_anomalies" in r for r in rows)
    assert rows[-1]["token_anomalies"] >= 1
    assert summary["token_trend"] is not None
    assert summary["token_trend"]["latest"] >= 1


def test_fleet_trend_prose_mentions_burn(tmp_path, capsys):
    import time

    import approximately.cli as cli
    from approximately.fleet import append_digest, digest_snapshot

    burn_dir = tmp_path / "burn"
    _store_with_burn(burn_dir)
    summaries = survey([burn_dir])
    digest_dir = tmp_path / "digest"
    for offset in (2, 1):
        snap = digest_snapshot(summaries)
        snap["ts"] = time.time() - offset * 86400
        append_digest(digest_dir, snap)
    args = argparse.Namespace(
        stores=[str(burn_dir)], digest_dir=str(digest_dir),
        trend=True, agent=None, json=False, fleet_html=None,
        top_agents=3, keep_days=30, watch=None, iterations=None,
        webhook=None, alert_anomalies=None, alert_tokens=None,
        alert_worse_than=None, fail_on_worsening=False)
    assert cli.cmd_fleet(args) == 0
    out = capsys.readouterr().out
    assert "token-burn trend" in out


def test_cli_fleet_json_token_fields(tmp_path, capsys):
    burn_dir = tmp_path / "burn"
    _store_with_burn(burn_dir)
    args = argparse.Namespace(
        stores=[str(burn_dir)], json=True, fleet_html=None,
        digest_dir=None, trend=False, agent=None, top_agents=3,
        watch=None, iterations=None, webhook=None,
        alert_anomalies=None, alert_tokens=None,
        alert_worse_than=None, fail_on_worsening=False,
        keep_days=30)
    assert cmd_fleet(args) == 0
    payload = json.loads(capsys.readouterr().out)
    entry = (payload.get("stores") or [payload])[0]
    summary = entry.get("summary", entry)
    assert summary["token_anomalies"] >= 1


def test_spend_trend_verdict(tmp_path):
    import time

    from approximately.fleet import (
        append_digest,
        digest_snapshot,
        summarize_trend,
        survey,
        trend_days,
    )

    burn_dir = tmp_path / "burn"
    _store_with_burn(burn_dir)
    summaries = survey([burn_dir],
                       prices={"gpt-x": 3.0, "unknown": 3.0})
    assert summaries[0].est_spend == 30.06     # 10,020 tok @ $3/1k
    digest_dir = tmp_path / "digest"
    for offset in (2, 1):
        snap = digest_snapshot(summaries)
        snap["ts"] = time.time() - offset * 86400
        append_digest(digest_dir, snap)
    summary = summarize_trend(trend_days(digest_dir))
    assert summary["spend_trend"] is not None
    assert summary["spend_trend"]["latest"] == 30.06
    assert summary["spend_trend"]["verdict"] in ("stable", "worsening",
                                                 "improving")
    for row in summary["days"]:
        assert row["est_spend"] == 30.06


def test_spend_trend_absent_without_prices(tmp_path):
    import time

    from approximately.fleet import (
        append_digest,
        digest_snapshot,
        summarize_trend,
        survey,
        trend_days,
    )

    burn_dir = tmp_path / "burn"
    _store_with_burn(burn_dir)
    summaries = survey([burn_dir])             # no prices in play
    digest_dir = tmp_path / "digest"
    for offset in (2, 1):
        snap = digest_snapshot(summaries)
        snap["ts"] = time.time() - offset * 86400
        append_digest(digest_dir, snap)
    summary = summarize_trend(trend_days(digest_dir))
    assert summary["spend_trend"] is None      # zeros: no verdict


def test_alert_spend_pages_on_expensive_store(tmp_path):
    burn_dir = tmp_path / "burn"
    _store_with_burn(burn_dir)
    summaries = survey([burn_dir], prices={"unknown": 3.0})
    assert summaries[0].est_spend > 25
    # the spend gate adds a fire condition (v162 contract)
    assert _should_alert(summaries, 0.99, alert_spend=25.0) is True
    assert _should_alert(summaries, 0.99, alert_spend=500.0) is False


def test_alert_spend_unpriced_never_trips(tmp_path):
    calm_dir = tmp_path / "calm"
    store = TraceStore(calm_dir)
    rec = Recorder("calm", save=False)
    rec.respond("done", success=True)
    store.save(rec.trace)
    summaries = survey([calm_dir])             # no prices: unpriced
    assert _should_alert(summaries, 0.99, alert_spend=0.01) is False


def test_watch_alert_spend_end_to_end(tmp_path):
    burn_dir = tmp_path / "burn"
    _store_with_burn(burn_dir)
    digest_dir = tmp_path / "digest"
    posts = []
    watch_fleet([burn_dir], digest_dir, interval=0.0, iterations=2,
                webhook_url="http://example.test/hook",
                notify=lambda summaries, url: posts.append(summaries),
                alert_worse_than=0.99, alert_spend=25.0,
                prices={"unknown": 3.0})
    assert len(posts) == 2
