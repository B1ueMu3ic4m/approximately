"""Fuzz 32: the digest dir lies to the trend chain.

The fleet trend reads ``digest-*.jsonl`` from a directory the
operator points at — files can hold torn lines, wrong shapes,
timestamps that lie, and snapshots whose ``stores`` is anything
but the list of dicts the code hopes for. The chain under fuzz:
trend_days -> summarize_trend -> week_compare / failure_budget /
forecast_spend. The contract: untrusted input degrades the
verdict, never the process — no raise escapes, and the shapes
the doors promise (verdict string, usable flag, day list) hold.
"""

import json
import tempfile
from pathlib import Path

from approximately.fleet import summarize_trend, trend_days, week_compare

LYING_SNAPSHOTS = [
    {"ts": "not a number", "stores": "the whole fleet, honest"},
    {"ts": 0, "stores": {"a": {"traces": 10, "failures": 5}}},
    {"ts": 1e18, "stores": [["a"], ["b"]]},
    {"ts": None, "stores": [{"traces": "ten", "failures": "5"}]},
    {"ts": -99999999999, "stores": [{"name": None}]},
    {"stores": [{"traces": 10, "failures": 5}],
     "ts": 1793312531},
    {"ts": 1793312531, "stores": [None, 7, "x"]},
    {"ts": 1793312531, "stores": [{"failures": 5},
                                  {"traces": 10}]},
]


def _dir_with(lines, name="digest-20261030.jsonl"):
    d = Path(tempfile.mkdtemp())
    (d / name).write_text("\n".join(lines) + "\n",
                          encoding="utf-8")
    return d


def test_the_chain_never_raises_on_lying_snapshots():
    lines = [json.dumps(s) if isinstance(s, dict) else s
             for s in LYING_SNAPSHOTS]
    rows = summarize_trend(trend_days(_dir_with(lines)))["days"]
    for row in rows:
        assert isinstance(row["day"], str)
        assert isinstance(row["failures"], int)
        assert isinstance(row["failure_rate"], float)
    wc = week_compare(rows)
    assert set(wc) >= {"usable", "this_week", "last_week",
                       "deltas"}


def test_torn_and_foreign_lines_degrade_silently():
    lines = ["not json", "[1, 2]", '"a string"', "123", "null",
             json.dumps({"ts": 1793312531,
                         "stores": [{"traces": 4, "failures": 1}]}),
             "", "   "]
    rows = summarize_trend(trend_days(_dir_with(lines)))["days"]
    assert len(rows) == 1, "only the real snapshot forms a day"
    assert rows[0]["traces"] == 4


def test_garbage_filename_falls_back_to_epoch_day():
    # the fallback fires only when the timestamp itself is corrupt;
    # a valid ts names the real day no matter what the file says
    lines = [json.dumps({"ts": "corrupt",
                         "stores": [{"traces": 4, "failures": 1}]})]
    rows = trend_days(_dir_with(lines, name="digest-garbage.jsonl"))
    assert rows[0]["day"] == "1970-01-01", \
        "no file stamp, corrupt timestamp: the epoch is the floor"
    good = trend_days(_dir_with(
        [json.dumps({"ts": 1793312531,
                     "stores": [{"traces": 4, "failures": 1}]})],
        name="digest-garbage.jsonl"))
    import datetime as dt
    expected = dt.datetime.fromtimestamp(1793312531).strftime(
        "%Y-%m-%d")  # the same local clock the code reads
    assert good[0]["day"] == expected, \
        "a valid timestamp wins even without a file stamp"


def test_budget_and_forecast_survive_the_same_rows():
    from approximately.forecast import failure_budget, forecast_spend

    lines = [json.dumps(s) for s in LYING_SNAPSHOTS
             if isinstance(s, dict)]
    rows = summarize_trend(trend_days(_dir_with(lines)))["days"]
    fb = failure_budget(rows, allowance=3)
    assert isinstance(fb.get("days_left"), int) or \
        fb.get("days_left") is None
    fs = forecast_spend(rows, ceiling=10.0)
    assert "projection" in fs
    wc = week_compare(rows)
    assert wc["usable"] in (True, False)
