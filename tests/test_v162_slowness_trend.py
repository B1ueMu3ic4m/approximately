"""v162: slowness gets a trend, and the glance keeps its tail.

Digest snapshots carry each store's fleet-anomaly count (v1.44's
webhook fields flow through), so the trend can judge slowness over
days: `trend.anomaly_trend` appears once there are two days of
history. Also restores the status tail lines (trend/ledger/
recidivist/last-failure-none) that the shared renderer dropped in
v1.42 — the one-shot has been delegating to it since.
"""

import argparse
import time

from approximately.cli import cmd_status
from approximately.fleet import append_digest, digest_snapshot, summarize_trend, survey, trend_days
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed(directory):
    store = TraceStore(directory)
    jitter = (1800, 2000, 2100, 1900)
    for i in range(4):
        rec = Recorder(f"boring {i}", save=False)
        rec.tool("search", {"q": str(i)}, result="hit")
        rec.respond("done", success=True)
        rec.trace.steps[0].latency_ms = jitter[i]
        store.save(rec.trace)
    slow = Recorder("the slow one", save=False)
    slow.tool("search", {"q": "heavy"}, result="hit")
    slow.respond("done", success=True)
    slow.trace.steps[0].latency_ms = 30000
    store.save(slow.trace)
    return store


def test_trend_row_sums_fleet_anomalies(tmp_path):
    store = _seed(tmp_path / "s")
    digest_dir = tmp_path / "d"
    summaries = survey([store.directory])
    append_digest(digest_dir, digest_snapshot(summaries))
    days = trend_days(digest_dir)
    assert days[0]["last"]["stores"][0]["fleet_anomalies"] == 1
    summary = summarize_trend(days)
    assert summary["days"][0]["fleet_anomalies"] == 1
    assert summary["anomaly_trend"] is None  # one day: no verdict


def test_two_days_give_a_slowness_verdict(tmp_path):
    import time

    store = _seed(tmp_path / "s")
    digest_dir = tmp_path / "d"
    summaries = survey([store.directory])
    for offset in (2, 1):
        snap = digest_snapshot(summaries)
        snap["ts"] = time.time() - offset * 86400
        append_digest(digest_dir, snap)
    summary = summarize_trend(trend_days(digest_dir))
    assert summary["anomaly_trend"] is not None
    assert summary["anomaly_trend"]["latest"] == 1


def test_status_prose_shows_tail_and_slowness(tmp_path, capsys):
    store = _seed(tmp_path / "s")
    digest_dir = tmp_path / "d"
    summaries = survey([store.directory])
    for offset in (2, 1):
        snap = digest_snapshot(summaries)
        snap["ts"] = time.time() - offset * 86400
        append_digest(digest_dir, snap)
    args = argparse.Namespace(store=str(store.directory), since=None,
                              digest_dir=str(digest_dir), json=False,
                              watch=False, interval=30.0, frames=None)
    assert cmd_status(args) == 0
    out = capsys.readouterr().out
    assert "slowness trend:" in out
    assert "last failure: none" in out
