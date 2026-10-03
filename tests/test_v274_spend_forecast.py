"""Night VI, round 18: the spend forecast.

The trend verdicts say which way; ``fleet --trend --spend-ceiling``
says how fast and what that means in days.  Theil-Sen slope over the
daily spend series, a horizon projection, days-to-ceiling (0 when
already over, ``None`` when the trend never gets there), and a
forecast that refuses to guess on one day of history.
"""

import json

from approximately.cli import _fleet_trend
from approximately.forecast import forecast_spend


def _day(day, spend):
    return {"day": day, "est_spend": spend}


def test_rising_series_projects_a_crossing():
    days = [_day(f"2026-10-0{d}", spend)
            for d, spend in enumerate([10, 20, 30, 40], start=1)]
    f = forecast_spend(days, ceiling=100.0)
    assert f["usable"] is True
    assert f["verdict"] == "worsening"
    assert f["latest"] == 40
    assert f["days_to_ceiling"] == 6  # (100-40)/10
    assert f["projection"][0]["day"] == "2026-10-05"
    assert f["projection"][-1]["day"] == "2026-10-18"


def test_flat_series_never_reaches():
    days = [_day(f"2026-10-0{d}", 5.0) for d in range(1, 5)]
    f = forecast_spend(days, ceiling=100.0)
    assert f["slope"] == 0
    assert f["days_to_ceiling"] is None


def test_falling_series_never_reaches():
    days = [_day(f"2026-10-0{d}", spend)
            for d, spend in enumerate([40, 30, 20, 10], start=1)]
    f = forecast_spend(days, ceiling=100.0)
    assert f["verdict"] == "improving"
    assert f["days_to_ceiling"] is None
    # the projection floors at zero — spend cannot go negative
    assert all(p["est_spend"] >= 0 for p in f["projection"])


def test_already_over_the_ceiling_is_zero_days():
    days = [_day("2026-10-01", 50), _day("2026-10-02", 60)]
    f = forecast_spend(days, ceiling=40.0)
    assert f["days_to_ceiling"] == 0


def test_one_day_refuses_to_guess():
    f = forecast_spend([_day("2026-10-01", 42.0)], ceiling=50.0)
    assert f["usable"] is False
    assert f["days_to_ceiling"] is None
    assert "two days" in f["reason"]


def test_projection_is_clamped_non_negative():
    days = [_day("2026-10-01", 1.0), _day("2026-10-02", 0.0)]
    f = forecast_spend(days, horizon_days=10)
    assert all(p["est_spend"] >= 0 for p in f["projection"])


def _write_days(digest, spend_by_day):
    """Write one compacted day file per entry (append_digest buckets
    by today, so a two-day history is written directly)."""
    import datetime
    digest.mkdir(parents=True, exist_ok=True)
    base = datetime.date(2026, 10, 1)
    for i, spend in enumerate(spend_by_day):
        stamp = (base + datetime.timedelta(days=i)).strftime("%Y%m%d")
        payload = {"ts": 1791000000 + i * 86400,
                   "stores": [{"name": "s", "path": "/s", "traces": 1,
                               "est_spend": spend,
                               "spend_unpriced_tokens": 0}],
                   "worsening": []}
        (digest / f"digest-{stamp}.jsonl").write_text(
            json.dumps(payload, sort_keys=True) + "\n",
            encoding="utf-8")


def test_cli_trend_with_ceiling(tmp_path, capsys):
    from pathlib import Path
    _write_days(Path(tmp_path / "d"), [0.01, 0.03])
    rc = _fleet_trend(argparse_ns(str(tmp_path / "d"),
                                  spend_ceiling=100.0))
    out = capsys.readouterr().out
    assert rc == 0
    assert "spend forecast:" in out
    assert "reached in ~4999 day(s) at this trend" in out
    assert "cannot see your next" in out


def test_cli_trend_json_carries_the_forecast(tmp_path, capsys):
    from pathlib import Path
    _write_days(Path(tmp_path / "d"), [0.5, 1.5])
    rc = _fleet_trend(argparse_ns(str(tmp_path / "d"),
                                  spend_ceiling=1.0, as_json=True))
    out = capsys.readouterr().out
    assert rc == 1  # already over the $1 ceiling
    payload = json.loads(out)
    assert payload["spend_forecast"]["days_to_ceiling"] == 0
    assert payload["spend_forecast"]["latest"] == 1.5


def argparse_ns(digest, spend_ceiling=None, as_json=False):
    import argparse
    return argparse.Namespace(digest_dir=digest, agent=None,
                              trend=True, json=as_json,
                              fail_on_worsening=False,
                              spend_ceiling=spend_ceiling)
