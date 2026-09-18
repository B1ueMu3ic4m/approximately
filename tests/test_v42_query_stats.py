"""v0.42 — query --stats: aggregates over a DSL selection."""

from __future__ import annotations

import argparse
import json

from approximately.cli import cmd_query
from approximately.query import summarize
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store_with(tmp_path):
    store = TraceStore(str(tmp_path / "traces"))
    specs = [
        ("q-ok", True, "fix the login bug", 3, 40),
        ("q-f1", False, "fix the login bug", 9, 400),
        ("q-f2", False, "write the docs", 5, 260),
    ]
    for tid, ok, task, n_steps, tokens in specs:
        rec = Recorder(task, save=False)
        rec.trace.id = tid
        for i in range(n_steps):
            step = rec.tool("bash", {"cmd": f"step {i}"},
                            result=f"out {i}")
            step.tokens = tokens // n_steps
        rec.respond("done" if ok else "gave up", success=ok)
        if not ok:
            rec.trace.meta["detections"] = [{"mode": "FM-3.2"}]
        store.save(rec.trace)
    return store


def _args(tmp_path, expression, stats=False, json_mode=False):
    return argparse.Namespace(store=str(tmp_path / "traces"),
                              expression=expression, stats=stats,
                              json=json_mode)


def test_summarize_counts_and_rates():
    class T:
        pass

    def mk(ok, n, toks):
        t = T()
        t.success = ok
        t.steps = [type("S", (), {"tokens": toks // n})() for _ in range(n)]
        t.meta = {}
        return t

    stats = summarize([mk(True, 2, 20), mk(False, 8, 40)])
    assert stats["count"] == 2
    assert stats["success"] == 1 and stats["failed"] == 1
    assert stats["failure_rate"] == 0.5
    assert stats["mean_steps"] == 5.0


def test_summarize_empty_selection():
    stats = summarize([])
    assert stats["count"] == 0 and stats["failure_rate"] == 0.0
    assert stats["modes"] == {}


def test_cli_stats_text(tmp_path, capsys):
    _store_with(tmp_path)
    rc = cmd_query(_args(tmp_path, "success == false", stats=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert "count 2" in out and "failed 2" in out
    assert "failure rate 100.0%" in out
    assert "FM-3.2 x2" in out
    # each record's respond step counts too: (9+1 + 5+1) / 2 = 8.0
    assert "mean steps 8.0" in out
    assert "mean tokens 328.0" in out


def test_cli_stats_json(tmp_path, capsys):
    _store_with(tmp_path)
    rc = cmd_query(_args(tmp_path, "task contains 'login'",
                         stats=True, json_mode=True))
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["count"] == 2
    assert payload["failed"] == 1
    assert payload["modes"] == {"FM-3.2": 1}


def test_cli_stats_zero_matches(tmp_path, capsys):
    _store_with(tmp_path)
    rc = cmd_query(_args(tmp_path, "task contains 'nonexistent'",
                         stats=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert "count 0" in out
