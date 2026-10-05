"""v295: the price catalog — rates that live with the store.

``prices.json`` in the store root, managed by ``approximately prices
set/unset``, consumed by every spend door that wasn't given an
explicit ``--prices``. Explicit wins. And retention must not eat the
furniture: ``clean`` once globbed every root ``*.json`` — the catalog
(and stats.json) would have aged out with the traces.
"""

import argparse
import contextlib
import io
import json
import time

import pytest

from approximately.cli import cmd_prices
from approximately.mcp_server import ServerContext, _tool_prices
from approximately.prices import (
    catalog_path,
    load_catalog,
    resolve_prices,
    set_rate,
    unset_rate,
    validate_table,
)
from approximately.store import TraceStore
from approximately.trace import Step, Trace


def test_set_unset_roundtrip(tmp_path):
    assert load_catalog(tmp_path) is None
    table = set_rate(tmp_path, "gpt-x", 0.5)
    assert table == {"gpt-x": 0.5}
    set_rate(tmp_path, "claude-y", 3.25)
    set_rate(tmp_path, "gpt-x", 0.75)  # upsert
    assert load_catalog(tmp_path) == {"gpt-x": 0.75, "claude-y": 3.25}
    assert catalog_path(tmp_path).name == "prices.json"
    unset_rate(tmp_path, "claude-y")
    assert load_catalog(tmp_path) == {"gpt-x": 0.75}
    with pytest.raises(KeyError, match="no rate on file"):
        unset_rate(tmp_path, "claude-y")


def test_validation_refusals():
    with pytest.raises(ValueError, match="must map model"):
        validate_table([1, 2])
    with pytest.raises(ValueError, match="must be a number"):
        validate_table({"m": "free"})
    with pytest.raises(ValueError, match="non-negative"):
        validate_table({"m": -0.1})
    with pytest.raises(ValueError, match="finite"):
        validate_table({"m": float("nan")})
    with pytest.raises(ValueError, match="bad model name"):
        validate_table({"": 1.0})
    with pytest.raises(ValueError, match="bad model name"):
        validate_table({3: 1.0})
    assert validate_table({"m": 0}) == {"m": 0.0}  # free is legal
    assert validate_table({"m": True}) if False else True
    with pytest.raises(ValueError, match="must be a number"):
        validate_table({"m": True})  # bool is not a rate


def test_corrupt_catalog_refuses(tmp_path):
    catalog_path(tmp_path).write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="price catalog"):
        load_catalog(tmp_path)
    with pytest.raises(ValueError):
        resolve_prices(tmp_path, None)


def test_resolve_explicit_wins(tmp_path):
    set_rate(tmp_path, "gpt-x", 0.5)
    explicit = tmp_path / "explicit.json"
    explicit.write_text(json.dumps({"other": 9.0}), encoding="utf-8")
    assert resolve_prices(tmp_path, str(explicit)) == {"other": 9.0}
    assert resolve_prices(tmp_path, None) == {"gpt-x": 0.5}
    assert resolve_prices(tmp_path, None) is not None
    missing = tmp_path / "nope.json"
    with pytest.raises(ValueError, match="prices file"):
        resolve_prices(tmp_path, str(missing))
    assert resolve_prices(tmp_path, None) is not None


def test_clean_spares_the_furniture(tmp_path):
    import os

    store = TraceStore(tmp_path)
    t = Trace(task="old run", model="m")
    t.add(Step(kind="tool_call", tool="sh", result="fine"))
    t.success = True
    t.created_at = time.time() - 90 * 86400
    path = store.save(t)
    old = time.time() - 90 * 86400
    os.utime(path, (old, old))  # clean judges file mtime
    set_rate(tmp_path, "gpt-x", 0.5)
    (tmp_path / "stats.json").write_text("{}", encoding="utf-8")
    removed = store.clean(keep_days=7)
    assert removed == 1
    assert not (tmp_path / f"{t.id}.json").exists()
    assert load_catalog(tmp_path) == {"gpt-x": 0.5}
    assert (tmp_path / "stats.json").exists()
    # max_traces branch spares them too
    t2 = Trace(task="new run", model="m")
    t2.add(Step(kind="tool_call", tool="sh", result="fine"))
    t2.success = True
    store.save(t2)
    assert store.clean(keep_days=3650, max_traces=1) == 0
    assert load_catalog(tmp_path) == {"gpt-x": 0.5}


def test_budget_door_falls_back_to_catalog(tmp_path):
    from approximately.cli import cmd_budget

    store = TraceStore(tmp_path)
    t = Trace(task="burn", model="gpt-x")
    t.add(Step(kind="tool_call", tool="sh", result="r", tokens=30_000))
    t.add(Step(kind="tool_call", tool="sh", result="r2", tokens=30_000))
    t.success = True
    store.save(t)
    set_rate(tmp_path, "gpt-x", 0.5)  # $15 per step; ceiling $10
    args = argparse.Namespace(store=str(tmp_path), trace=t.id,
                              tokens=None, usd=10.0,
                              prices=None, on_exceed="stamp",
                              agent=None, **{"json": True})
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert cmd_budget(args) == 0
    payload = json.loads(buf.getvalue())
    assert payload["would_trip"] is True
    assert payload["saved_usd"] == 15.0  # the catalog priced it


def test_cli_list_set_unset(tmp_path, capsys):
    base = {"store": str(tmp_path)}
    assert cmd_prices(argparse.Namespace(
        **base, json=False)) == 0
    assert "no rates on file" in capsys.readouterr().out
    assert cmd_prices(argparse.Namespace(
        **base, json=False, prices_op="set", model="gpt-x",
        rate="0.5")) == 0
    out = capsys.readouterr().out
    assert "gpt-x" in out and "0.5" in out
    assert cmd_prices(argparse.Namespace(
        **base, json=True)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["prices"] == {"gpt-x": 0.5}
    assert cmd_prices(argparse.Namespace(
        **base, prices_op="unset", model="gpt-x", rate=None)) == 0
    capsys.readouterr()
    assert cmd_prices(argparse.Namespace(
        **base, prices_op="unset", model="ghost",
        rate=None)) == 2
    assert cmd_prices(argparse.Namespace(
        **base, prices_op="set", model="m", rate="nan",
        json=False)) == 2
    assert cmd_prices(argparse.Namespace(
        **base, prices_op="set", model="m", rate="-1")) == 2
    assert cmd_prices(argparse.Namespace(
        **base, prices_op="set", model="m", rate="abc")) == 2


def test_mcp_prices(tmp_path):
    ctx = ServerContext(str(tmp_path))
    got = _tool_prices(ctx, {})
    assert got["prices"] == {}
    _tool_prices(ctx, {"op": "set", "model": "gpt-x", "rate": 0.5})
    got = _tool_prices(ctx, {})
    assert got["prices"] == {"gpt-x": 0.5}
    _tool_prices(ctx, {"op": "unset", "model": "gpt-x"})
    assert _tool_prices(ctx, {})["prices"] == {}
    with pytest.raises(KeyError, match="needs model and rate"):
        _tool_prices(ctx, {"op": "set", "model": "m"})
    with pytest.raises(KeyError, match="no rate on file"):
        _tool_prices(ctx, {"op": "unset", "model": "ghost"})
    with pytest.raises(KeyError, match="refused"):
        _tool_prices(ctx, {"op": "set", "model": "m", "rate": -1})
