"""Night VII, round 1: the reliability budget.

Money got a forecast in v2.87; reliability gets the same accounting
now.  ``fleet --trend --failure-budget N`` treats the window's failed
runs as a burn against an allowance — burn fraction, exhaustion date
from the Theil-Sen slope, exit 1 when already gone.  The digest
payloads carry the exact ``failures`` count per store and per day.
"""

import json

from approximately.cli import _fleet_trend, main
from approximately.fleet import (
    webhook_payload,
)
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _burn(store_dir, failures=1):
    store = TraceStore(store_dir)
    for i in range(failures):
        with Recorder(f"fail {i}", model="m/1", store=store,
                      save=False) as rec:
            rec.tool("t", tokens=10)
            rec.respond("broken", success=False)
        store.save(rec.trace)


def _write_days(digest, failures_by_day):
    import datetime
    digest.mkdir(parents=True, exist_ok=True)
    base = datetime.date(2026, 10, 1)
    for i, failures in enumerate(failures_by_day):
        stamp = (base + datetime.timedelta(days=i)).strftime("%Y%m%d")
        payload = {
            "ts": 1791000000 + i * 86400,
            "stores": [{"name": "s", "path": "/s", "traces": 10,
                        "failures": failures, "failure_rate":
                            failures / 10}],
            "worsening": []}
        (digest / f"digest-{stamp}.jsonl").write_text(
            json.dumps(payload, sort_keys=True) + "\n",
            encoding="utf-8")


def test_payload_and_rows_carry_exact_failures(tmp_path):
    store_dir = tmp_path / "s"
    _burn(store_dir, failures=2)
    from approximately.fleet import survey
    payload = webhook_payload(survey([store_dir]))
    assert payload["stores"][0]["failures"] == 2


def test_failure_budget_burn_and_exhaustion():
    from approximately.forecast import failure_budget
    days = [{"day": f"2026-10-0{d}", "failures": f}
            for d, f in zip(range(1, 5), [2, 3, 5, 6])]
    fb = failure_budget(days, allowance=20)
    assert fb["usable"] is True
    assert fb["burned"] == 16
    assert fb["burn_fraction"] == 0.8
    assert fb["days_to_exhaustion"] == 3
    assert fb["projection"][-1]["remaining"] == 0


def test_failure_budget_refuses_one_day():
    from approximately.forecast import failure_budget
    fb = failure_budget([{"day": "2026-10-01", "failures": 1}],
                        allowance=10)
    assert fb["usable"] is False
    assert "two days" in fb["reason"]


def test_failure_budget_never_exhausted_when_improving():
    from approximately.forecast import failure_budget
    days = [{"day": f"2026-10-0{d}", "failures": f}
            for d, f in zip(range(1, 5), [9, 7, 5, 3])]
    fb = failure_budget(days, allowance=30)
    assert fb["days_to_exhaustion"] is None
    assert all(p["remaining"] >= 0 for p in fb["projection"])


def test_failure_budget_already_gone_is_zero_days():
    from approximately.forecast import failure_budget
    days = [{"day": "2026-10-01", "failures": 5},
            {"day": "2026-10-02", "failures": 8}]
    fb = failure_budget(days, allowance=6)
    assert fb["exhausted"] is True
    assert fb["days_to_exhaustion"] == 0


def test_fleet_trend_reports_the_budget(tmp_path, capsys):
    digest = tmp_path / "d"
    _write_days(digest, [2, 4])
    args = argparse_ns(str(digest), failure_budget=10)
    rc = _fleet_trend(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "failure budget: 6/10 failed runs (60% burned)" in out


def test_fleet_trend_exhausted_exits_one(tmp_path, capsys):
    digest = tmp_path / "d"
    _write_days(digest, [9, 9])
    args = argparse_ns(str(digest), failure_budget=10)
    rc = _fleet_trend(args)
    capsys.readouterr()
    assert rc == 1


def test_fleet_trend_json_carries_the_budget(tmp_path, capsys):
    digest = tmp_path / "d"
    _write_days(digest, [2, 4])
    args = argparse_ns(str(digest), failure_budget=10, as_json=True)
    rc = _fleet_trend(args)
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["failure_budget"]["burned"] == 6
    assert payload["days"][0]["failures"] == 2


def test_audit_door_fails_on_exhausted_budget(tmp_path, capsys):
    store = TraceStore(tmp_path / "s")
    with Recorder("calm", model="m/1", store=store) as rec:
        rec.respond("done", success=True)
    digest = tmp_path / "d"
    _write_days(digest, [9, 9])
    rc = main(["audit", "--store", str(store.directory),
               "--min-traces", "1", "--digest-dir", str(digest),
               "--failure-budget", "10", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["failure_budget"]["exhausted"] is True
    assert payload["ok"] is False


def argparse_ns(digest, failure_budget=None, as_json=False):
    import argparse
    return argparse.Namespace(digest_dir=digest, agent=None,
                              trend=True, json=as_json,
                              fail_on_worsening=False,
                              spend_ceiling=None,
                              failure_budget=failure_budget)
