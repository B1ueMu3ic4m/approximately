"""v362: the trend chain sees the deliveries.

The digest history's store rows carry inbox_rows / inbox_verified
(v3.62.0); the trend chain aggregates them per day — the fleet can
trend its own deliveries beside its failures. Older snapshots
without the fields degrade to zero, the row's own rule.
"""

import json
import tempfile
from pathlib import Path

from approximately.fleet import summarize_trend, trend_days


def _dir_with(stores_by_day):
    import datetime as dt
    d = Path(tempfile.mkdtemp())
    for day, stores in stores_by_day.items():
        ts = dt.datetime.fromisoformat(
            f"{day}T12:00:00+00:00").timestamp()
        snap = {"ts": ts, "worsening": [], "stores": stores}
        (d / f"digest-{day.replace('-', '')}.jsonl").write_text(
            json.dumps(snap) + "\n", encoding="utf-8")
    return d


def test_trend_days_aggregate_the_inbox():
    d = _dir_with({
        "2026-10-30": [{"traces": 10, "failures": 1,
                        "inbox_rows": 12, "inbox_verified": 9},
                       {"traces": 5, "failures": 0,
                        "inbox_rows": 4, "inbox_verified": 4}],
        "2026-10-31": [{"traces": 8, "failures": 2,
                        "inbox_rows": 3, "inbox_verified": 0}],
    })
    days = summarize_trend(trend_days(d))["days"]
    by_day = {r["day"]: r for r in days}
    assert by_day["2026-10-30"]["inbox_rows"] == 16
    assert by_day["2026-10-30"]["inbox_verified"] == 13
    assert by_day["2026-10-31"]["inbox_rows"] == 3


def test_old_snapshots_degrade_to_zero():
    d = _dir_with({"2026-10-30": [{"traces": 4, "failures": 1}]})
    days = summarize_trend(trend_days(d))["days"]
    assert days[0]["inbox_rows"] == 0
    assert days[0]["inbox_verified"] == 0


def test_lying_stores_degrade_the_inbox_too():
    d = _dir_with({"2026-10-30": [{"traces": 4, "failures": 1},
                                  "not a store",
                                  {"inbox_rows": "lots"}]})
    days = summarize_trend(trend_days(d))["days"]
    assert days[0]["inbox_rows"] == 0, \
        "a lying count is not a count"
    assert days[0]["inbox_verified"] == 0


def test_lying_numeric_fields_degrade_everywhere():
    d = _dir_with({"2026-10-30": [
        {"traces": "ten", "failures": "five",
         "budget_breaches": "many", "fleet_anomalies": [1],
         "result_anomalies": None, "est_spend": "free"}]})
    days = summarize_trend(trend_days(d))["days"]
    r = days[0]
    assert r["traces"] == 0 and r["failures"] == 0
    assert r["budget_breaches"] == 0 and r["fleet_anomalies"] == 0
    assert r["result_anomalies"] == 0
    assert r["est_spend"] == 0.0, "spend lies degrade too"
