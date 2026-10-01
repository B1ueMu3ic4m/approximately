"""v225: `stats --prices FILE` — models price differently.

A blended rate treats a $0.50 mini and a $15 reasoning model as the
same line item; the prices table prices each trace by its recorded
model, and models without a rate stay honestly unpriced instead of
silently costing zero.
"""

import argparse
import json

import pytest

from approximately.cli import cmd_stats
from approximately.store import TraceStore
from approximately.trace import Step, Trace


def _seed(path):
    store = TraceStore(path)
    for model, ident, tokens in (("gpt-x", "aaa000000000", 10_000),
                                 ("cheap", "bbb000000000", 5_000),
                                 ("mystery", "ccc000000000", 7_000)):
        trace = Trace(task=f"run {model}", id=ident, model=model,
                      success=True)
        trace.add(Step(kind="tool_call", tool="t", tokens=tokens))
        store.save(trace)
    return store


def _prices(tmp_path):
    table = tmp_path / "prices.json"
    table.write_text(json.dumps({"gpt-x": 3.0, "cheap": 0.5}),
                     encoding="utf-8")
    return table


def _args(store, prices, as_json=True):
    return argparse.Namespace(store=str(store), by_agent=False,
                              by_tool=False, min_failed=None,
                              trend=False, trend_bucket_days=1,
                              since=None, price_per_1k=None,
                              prices=str(prices) if prices else None,
                              json=as_json)


def test_spend_by_model_json(tmp_path, capsys):
    store = _seed(tmp_path / "s")
    args = _args(store.directory, _prices(tmp_path))
    assert cmd_stats(args) == 0
    payload = json.loads(capsys.readouterr().out)
    rows = {r["model"]: r for r in payload["spend_by_model"]}
    assert rows["gpt-x"]["est_cost"] == 30.0
    assert rows["cheap"]["est_cost"] == 2.5
    assert rows["mystery"]["est_cost"] is None
    assert payload["estimated_cost"] == 32.5
    assert payload["unpriced_tokens"] == 7_000


def test_spend_by_model_prose(tmp_path, capsys):
    store = _seed(tmp_path / "s")
    args = _args(store.directory, _prices(tmp_path), as_json=False)
    assert cmd_stats(args) == 0
    out = capsys.readouterr().out
    assert "unpriced" in out
    assert "$32.50" in out
    assert "no rate in the table" in out


def test_missing_rate_is_not_silent_zero(tmp_path, capsys):
    # the whole point: a model missing from the table must never
    # look free
    store = _seed(tmp_path / "s")
    table = tmp_path / "thin.json"
    table.write_text(json.dumps({"gpt-x": 3.0}), encoding="utf-8")
    args = _args(store.directory, table)
    assert cmd_stats(args) == 0
    payload = json.loads(capsys.readouterr().out)
    priced = {r["model"]: r for r in payload["spend_by_model"]}
    assert priced["mystery"]["est_cost"] is None
    assert payload["unpriced_tokens"] == 12_000  # cheap + mystery


def test_bad_prices_file_exits_loud(tmp_path, capsys):
    store = _seed(tmp_path / "s")
    bad = tmp_path / "bad.json"
    bad.write_text("{ nope", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        cmd_stats(_args(store.directory, bad))
    assert exc.value.code == 2


def test_prices_table_must_map_to_numbers(tmp_path):
    store = _seed(tmp_path / "s")
    bad = tmp_path / "wrong.json"
    bad.write_text(json.dumps({"gpt-x": "expensive"}),
                   encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        cmd_stats(_args(store.directory, bad))
    assert exc.value.code == 2
