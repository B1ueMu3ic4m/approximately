"""v0.39 — first-fault bisect: earliest material divergence."""

from __future__ import annotations

import json

from approximately.cli import cmd_bisect
from approximately.diff import diff, first_fault
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _trace(tmp_path, tid, steps):
    rec = Recorder("ship the release", save=False)
    rec.trace.id = tid
    for args, text in steps:
        rec.tool("assistant", args, result=text)
    rec.respond("done", success=True)
    TraceStore(str(tmp_path)).save(rec.trace)
    return rec.trace


def _s(path_arg, text):
    return ({"path": path_arg}, text)


def test_first_fault_is_earliest_divergence(tmp_path):
    # a (tool, args) pair that differs from the successful run's pair
    # registers as MUTATED — same-id pairs are EQUAL by alignment
    # semantics regardless of results
    a = _trace(tmp_path, "b-a", [_s("a", "alpha"), _s("b", "beta ok"),
                                 _s("c", "gamma ok")])
    b = _trace(tmp_path, "b-b", [_s("a", "alpha"), _s("b2", "BETA DIVERGED"),
                                 _s("c", "gamma ok")])
    fault = first_fault(diff(a, b))
    assert fault is not None
    assert fault.a_index == 1 and fault.b_index == 1
    assert fault.a_tool == "assistant"


def test_first_fault_none_on_identical_traces(tmp_path):
    a = _trace(tmp_path, "b-c", [_s("a", "alpha"), _s("b", "beta ok")])
    b = _trace(tmp_path, "b-d", [_s("a", "alpha"), _s("b", "beta ok")])
    assert first_fault(diff(a, b)) is None


def test_floor_skips_benign_mutations(tmp_path):
    # position 1 mutates with near-identical results (timestamp noise);
    # position 2 mutates for real — the floor decides which is the fault
    noise = "beta ok [ts 2026-09-18T00:00:00]"
    clean = "beta ok [ts 2026-09-18T00:00:01]"
    a = _trace(tmp_path, "b-e", [_s("a", "alpha"), _s("b1", noise),
                                 _s("c1", "gamma CATASTROPHIC MISMATCH")])
    b = _trace(tmp_path, "b-f", [_s("a", "alpha"), _s("b2", clean),
                                 _s("c2", "gamma ok fine")])
    td = diff(a, b)
    assert first_fault(td, floor=0.8).a_index == 2
    assert first_fault(td, floor=1.01).a_index == 1


def test_deleted_step_is_material_regardless_of_floor(tmp_path):
    a = _trace(tmp_path, "b-g", [_s("a", "alpha"), _s("b", "beta ok")])
    b = _trace(tmp_path, "b-h", [_s("a", "alpha")])
    td = diff(a, b)
    fault = first_fault(td, floor=0.8)
    assert fault is not None and fault.a_index == 1


def test_cli_bisect_json(tmp_path, capsys):
    _trace(tmp_path, "b-i", [_s("a", "alpha"), _s("b", "beta ok")])
    _trace(tmp_path, "b-j", [_s("a", "alpha"), _s("b2", "BETA BAD")])
    rc = cmd_bisect(_args(tmp_path, "b-i", "b-j", json_mode=True))
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["a_id"] == "b-i" and out["b_id"] == "b-j"
    assert out["first_fault"]["a_index"] == 1
    assert out["divergences"] and out["divergences"][0]["similarity"] <= 1


def test_cli_bisect_text_reports_first_fault(tmp_path, capsys):
    _trace(tmp_path, "b-k", [_s("a", "alpha"), _s("b", "beta ok")])
    _trace(tmp_path, "b-l", [_s("a", "alpha"), _s("b2", "BETA BAD")])
    rc = cmd_bisect(_args(tmp_path, "b-k", "b-l"))
    text = capsys.readouterr().out
    assert rc == 0
    assert "first material divergence at step #1" in text
    assert "worst divergences" in text


def test_cli_bisect_identical_traces_exit_one(tmp_path, capsys):
    _trace(tmp_path, "b-m", [_s("a", "alpha")])
    _trace(tmp_path, "b-n", [_s("a", "alpha")])
    rc = cmd_bisect(_args(tmp_path, "b-m", "b-n"))
    text = capsys.readouterr().out
    assert rc == 1
    assert "no material divergence" in text


def _args(tmp_path, trace, other, json_mode=False):
    import argparse

    return argparse.Namespace(
        store=str(tmp_path), trace=trace, other=other,
        floor=0.8, json=json_mode)
