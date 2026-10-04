"""Night VII, round 21: the per-agent failure budget.

``fleet --trend --agent NAME --failure-budget N`` — the per-agent
story closes: rails (v2.80), sizing (v2.94), and now the agent's
own failed-run accounting against an allowance, read from the
digest's agent day-rows.
"""

import json

from approximately.cli import _fleet_trend


def _write_agent_days(tmp_path, failed_by_day):
    import datetime
    digest = tmp_path / "d"
    digest.mkdir(parents=True, exist_ok=True)
    base = datetime.date(2026, 10, 1)
    for i, failed in enumerate(failed_by_day):
        stamp = (base + datetime.timedelta(days=i)).strftime("%Y%m%d")
        snap = {
            "ts": 1791000000 + i * 86400,
            "stores": [{"name": "s", "path": "/s", "traces": 10,
                        "top_agents": [
                            {"agent": "researcher", "steps": 50,
                             "tool_calls": 40, "errors": 0,
                             "tokens": 100, "failed_traces": failed,
                             "failure_rate": failed / 10}]}],
            "worsening": []}
        (digest / f"digest-{stamp}.jsonl").write_text(
            json.dumps(snap, sort_keys=True) + "\n",
            encoding="utf-8")
    return digest


def _args(digest, failure_budget=None, as_json=False):
    import argparse
    return argparse.Namespace(digest_dir=digest, agent="researcher",
                              trend=True, json=as_json,
                              fail_on_worsening=False,
                              spend_ceiling=None,
                              failure_budget=failure_budget)


def test_agent_budget_burn(tmp_path, capsys):
    digest = _write_agent_days(tmp_path, [2, 4])
    rc = _fleet_trend(_args(str(digest), failure_budget=10))
    out = capsys.readouterr().out
    assert rc == 0
    assert "failure budget: 6/10 failed runs (60% burned)" in out


def test_agent_budget_json(tmp_path, capsys):
    digest = _write_agent_days(tmp_path, [9, 9])
    rc = _fleet_trend(_args(str(digest), failure_budget=10,
                            as_json=True))
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0  # agent-trend door never exits 1 on the budget
    fb = payload["failure_budget"]
    assert fb["burned"] == 18
    assert fb["exhausted"] is True


def test_no_allowance_no_budget_key(tmp_path, capsys):
    digest = _write_agent_days(tmp_path, [1, 1])
    rc = _fleet_trend(_args(str(digest), as_json=True))
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert "failure_budget" not in payload or \
        payload["failure_budget"] is None
