"""v0.40 — digest trend analytics: fleet --trend over daily snapshots."""

from __future__ import annotations

import json
import time

import pytest

from approximately.cli import _fleet_trend
from approximately.fleet import (
    digest_snapshot,
    render_trend,
    summarize_trend,
    trend_days,
)


def _summary(name, traces, failed, modes, worsening):
    class S:
        pass

    s = S()
    s.name, s.path = name, f"/tmp/{name}"
    s.traces = traces
    s.failed = failed
    s.failure_rate = failed / traces if traces else 0.0
    s.top_modes = modes
    s.trend_verdict = "worsening" if worsening else "stable"
    s.trend_slope = 0.2 if worsening else 0.0
    s.ledger_intact = None
    s.worsening = bool(worsening)
    return s


def _write_day(digest_dir, stamp, base_ts, stores, worsening=()):
    snap = digest_snapshot(stores)
    snap["ts"] = base_ts
    snap["worsening"] = list(worsening)
    # append_digest stamps the file from *now*; write with the wanted
    # day stamp instead so multi-day histories are testable
    path = digest_dir / f"digest-{stamp}.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(snap, sort_keys=True) + "\n")
    return snap


def test_trend_days_last_snapshot_per_day(tmp_path):
    a = _summary("core", 10, 4, [("FM-2.1", 2)], False)
    b = _summary("core", 12, 5, [("FM-2.1", 3)], False)
    _write_day(tmp_path, "20260916", 1_000_000, [a])
    _write_day(tmp_path, "20260917", 1_900_000, [a])
    _write_day(tmp_path, "20260917", 1_950_000, [b])  # later same day
    days = trend_days(tmp_path)
    assert len(days) == 2
    assert days[0]["snapshots"] == 1
    assert days[1]["snapshots"] == 2
    assert days[1]["last"]["stores"][0]["traces"] == 12


def test_trend_days_skips_torn_lines(tmp_path):
    path = tmp_path / "digest-20260918.jsonl"
    snap = json.dumps({"ts": time.time(), "stores": [], "worsening": []})
    path.write_text(snap + "\n" + '{"ts": torn', encoding="utf-8")
    days = trend_days(tmp_path)
    assert len(days) == 1 and days[0]["snapshots"] == 1


def test_corrupt_timestamp_falls_back_to_file_day(tmp_path):
    path = tmp_path / "digest-20260918.jsonl"
    path.write_text('{"ts": "not-a-number", "stores": [], '
                    '"worsening": []}\n', encoding="utf-8")
    days = trend_days(tmp_path)
    assert [d["day"] for d in days] == ["2026-09-18"]


def test_summarize_trend_verdict_and_modes(tmp_path):
    base = time.time() - 86400
    day1 = [_summary("core", 10, 3, [("FM-2.1", 2), ("FM-3.2", 1)], False)]
    day2 = [_summary("core", 10, 6, [("FM-2.1", 3), ("FM-3.2", 2)], True)]
    _write_day(tmp_path, "20260916", base, day1)
    _write_day(tmp_path, "20260917", time.time(), day2, worsening=["core"])
    summary = summarize_trend(trend_days(tmp_path))
    assert summary["days"][0]["failure_rate"] == pytest.approx(0.3)
    assert summary["days"][1]["failure_rate"] == pytest.approx(0.6)
    assert summary["days"][1]["worsening"] == ["core"]
    assert summary["days"][0]["top_modes"][0][0] == "FM-2.1"
    assert summary["verdict"] in ("improving", "stable", "worsening")
    assert summary["snapshots"] == 2


def test_render_trend_includes_sparkline_and_verdict(tmp_path):
    base = time.time() - 86400
    day1 = [_summary("core", 10, 3, [("FM-2.1", 2)], False)]
    day2 = [_summary("core", 10, 6, [("FM-2.1", 3)], True)]
    _write_day(tmp_path, "20260916", base, day1)
    _write_day(tmp_path, "20260917", time.time(), day2, worsening=["core"])
    text = render_trend(summarize_trend(trend_days(tmp_path)))
    assert "fleet trend - 2 day(s), 2 snapshot(s)" in text
    assert "sparkline" in text
    assert "verdict:" in text
    assert "FM-2.1 x3" in text


def test_render_trend_empty(tmp_path):
    text = render_trend(summarize_trend(trend_days(tmp_path)))
    assert "no digest snapshots" in text


def test_cli_trend_json_and_worsening_gate(tmp_path, capsys):
    base = time.time() - 86400
    day1 = [_summary("core", 10, 3, [("FM-2.1", 2)], False)]
    day2 = [_summary("core", 10, 9, [("FM-2.1", 5)], True)]
    _write_day(tmp_path, "20260916", base, day1)
    _write_day(tmp_path, "20260917", time.time(), day2, worsening=["core"])
    import argparse

    rc = _fleet_trend(argparse.Namespace(
        digest_dir=str(tmp_path), json=True, fail_on_worsening=True))
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1  # steep upward slope -> worsening -> CI gate trips
    assert payload["days"][1]["traces"] == 10
    assert payload["verdict"] == "worsening"


def test_trend_exit_zero_when_stable(tmp_path, capsys):
    base = time.time() - 86400
    day1 = [_summary("core", 10, 5, [("FM-2.1", 2)], False)]
    day2 = [_summary("core", 10, 5, [("FM-2.1", 2)], False)]
    _write_day(tmp_path, "20260916", base, day1)
    _write_day(tmp_path, "20260917", time.time(), day2)
    import argparse

    rc = _fleet_trend(argparse.Namespace(
        digest_dir=str(tmp_path), json=False, fail_on_worsening=True))
    assert rc == 0
    out = capsys.readouterr().out
    assert "verdict:" in out
