"""v220: `stats --price-per-1k` — the money number for "too big wastes
money".

The README has always claimed it tells you how big the context window
should be; this puts a dollar figure next to the token counts the
recorder already keeps.  Honest limits, stated in the output: the
recorder keeps one blended token count per step (no in/out split), so
the estimate takes a single blended rate.
"""

import argparse
import json

from approximately.cli import cmd_stats
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed(path):
    store = TraceStore(path)
    rec = Recorder("priced run", save=False)
    for i in range(4):
        rec.tool("search", {"q": str(i)}, result="hit")
        rec.trace.steps[-1].tokens = 2_000
    rec.respond("done", success=True)
    store.save(rec.trace)
    rec2 = Recorder("second run", save=False)
    rec2.respond("done", success=True)
    rec2.trace.steps[0].tokens = 1_000
    store.save(rec2.trace)
    return store


def test_tokens_summed_without_price(tmp_path, capsys):
    store = _seed(tmp_path / "s")
    args = argparse.Namespace(store=str(store.directory),
                              by_agent=False, by_tool=False,
                              min_failed=None, trend=False,
                              trend_bucket_days=1, since=None,
                              price_per_1k=None, json=True)
    assert cmd_stats(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["total_tokens"] == 9_000
    assert "estimated_cost" not in payload


def test_cost_estimate_in_json(tmp_path, capsys):
    store = _seed(tmp_path / "s")
    args = argparse.Namespace(store=str(store.directory),
                              by_agent=False, by_tool=False,
                              min_failed=None, trend=False,
                              trend_bucket_days=1, since=None,
                              price_per_1k=3.0, json=True)
    assert cmd_stats(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["price_per_1k"] == 3.0
    assert payload["estimated_cost"] == 27.0


def test_cost_estimate_in_prose(tmp_path, capsys):
    store = _seed(tmp_path / "s")
    args = argparse.Namespace(store=str(store.directory),
                              by_agent=False, by_tool=False,
                              min_failed=None, trend=False,
                              trend_bucket_days=1, since=None,
                              price_per_1k=2.0, json=False)
    assert cmd_stats(args) == 0
    out = capsys.readouterr().out
    assert "tokens: 9,000" in out
    assert "$18.00" in out
    assert "no in/out split" in out


def test_empty_store_prints_no_token_line(tmp_path, capsys):
    TraceStore(tmp_path / "s")
    args = argparse.Namespace(store=str(tmp_path / "s"),
                              by_agent=False, by_tool=False,
                              min_failed=None, trend=False,
                              trend_bucket_days=1, since=None,
                              price_per_1k=2.0, json=False)
    assert cmd_stats(args) == 0
    assert "tokens:" not in capsys.readouterr().out


def test_by_tool_cost_column(tmp_path, capsys):
    store = _seed(tmp_path / "s")
    args = argparse.Namespace(store=str(store.directory),
                              by_agent=False, by_tool=True,
                              min_failed=None, trend=False,
                              trend_bucket_days=1, since=None,
                              price_per_1k=2.0, json=True)
    assert cmd_stats(args) == 0
    rows = json.loads(capsys.readouterr().out)
    by_tool = {r["tool"]: r for r in rows}
    assert by_tool["search"]["tokens"] == 8_000
    assert by_tool["search"]["est_cost"] == 16.0


def test_by_tool_cost_prose(tmp_path, capsys):
    store = _seed(tmp_path / "s")
    args = argparse.Namespace(store=str(store.directory),
                              by_agent=False, by_tool=True,
                              min_failed=None, trend=False,
                              trend_bucket_days=1, since=None,
                              price_per_1k=2.0, json=False)
    assert cmd_stats(args) == 0
    out = capsys.readouterr().out
    assert "est $" in out
    assert "16.00" in out


def test_by_agent_cost_column(tmp_path, capsys):
    store = _seed(tmp_path / "s")
    trace = store.list_traces()[0]
    trace.steps[0].agent = "worker"
    store.save(trace)
    args = argparse.Namespace(store=str(store.directory),
                              by_agent=True, by_tool=False,
                              min_failed=None, trend=False,
                              trend_bucket_days=1, since=None,
                              price_per_1k=2.0, json=True)
    assert cmd_stats(args) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["est_cost"] >= 0
