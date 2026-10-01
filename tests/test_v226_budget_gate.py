"""v226: `stats --fail-over USD` — the spend estimate becomes an alarm.

The money number is only useful if something wakes you up: with a
price in play (--prices or --price-per-1k), --fail-over exits 1
when the estimate crosses the budget — cron/CI gets a gate without
a webhook.  Without a price the flag is a loud configuration error,
not a silent pass.
"""

import argparse
import json

from approximately.cli import cmd_stats
from approximately.store import TraceStore
from approximately.trace import Step, Trace


def _seed(path, tokens=10_000):
    store = TraceStore(path)
    trace = Trace(task="priced", id="aaa000000000", model="gpt-x",
                  success=True)
    trace.add(Step(kind="tool_call", tool="t", tokens=tokens))
    store.save(trace)
    return store


def _prices(tmp_path, rate=3.0):
    table = tmp_path / "prices.json"
    table.write_text(json.dumps({"gpt-x": rate}), encoding="utf-8")
    return table


def _run(store, tmp_path, **kw):
    ns = {"store": str(store.directory), "by_agent": False,
          "by_tool": False, "min_failed": None, "trend": False,
          "trend_bucket_days": 1, "since": None, "price_per_1k": None,
          "prices": str(_prices(tmp_path)), "json": True}
    ns.update(kw)
    return cmd_stats(argparse.Namespace(**ns))


def test_under_budget_exits_zero(tmp_path):
    store = _seed(tmp_path / "s")           # 10k tokens @ $3/1k = $30
    assert _run(store, tmp_path, fail_over=30.0) == 0


def test_over_budget_exits_one_with_message(tmp_path, capsys):
    store = _seed(tmp_path / "s")
    code = _run(store, tmp_path, fail_over=10.0)
    assert code == 1
    err = capsys.readouterr().err
    assert "budget exceeded" in err
    assert "$30.00" in err and "$10.00" in err


def test_works_with_blended_rate_too(tmp_path):
    store = _seed(tmp_path / "s")
    args = argparse.Namespace(
        store=str(store.directory), by_agent=False, by_tool=False,
        min_failed=None, trend=False, trend_bucket_days=1,
        since=None, prices=None, json=True,
        price_per_1k=2.0, fail_over=10.0)
    assert cmd_stats(args) == 1


def test_without_a_price_is_a_loud_config_error(tmp_path, capsys):
    store = _seed(tmp_path / "s")
    args = argparse.Namespace(
        store=str(store.directory), by_agent=False, by_tool=False,
        min_failed=None, trend=False, trend_bucket_days=1,
        since=None, prices=None, json=True,
        price_per_1k=None, fail_over=10.0)
    # handler-level contract: exit code 2 and a stderr explanation
    # (via main() that becomes the process exit)
    assert cmd_stats(args) == 2
    assert "needs a price in play" in capsys.readouterr().err


def test_over_budget_survives_empty_store(tmp_path):
    # an empty store prices to $0: under any budget, exit 0
    TraceStore(tmp_path / "empty")
    args = argparse.Namespace(
        store=str(tmp_path / "empty"), by_agent=False, by_tool=False,
        min_failed=None, trend=False, trend_bucket_days=1,
        since=None, prices=None, json=True,
        price_per_1k=2.0, fail_over=10.0)
    assert cmd_stats(args) == 0
