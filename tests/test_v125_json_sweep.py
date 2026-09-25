"""v124: the --json sweep completes — optimize, calibrate, explain,
taxonomy all speak machine too.

Every analysis/reference command in the CLI now has a structured
output path; the docs audit found these four were the last
prose-only holdouts.
"""

import argparse
import json

from approximately.cli import build_parser, cmd_annotations


def _run(*args):
    parser = build_parser()
    parsed = parser.parse_args(list(args))
    return parsed


def test_taxonomy_json_is_full_table(capsys):
    args = _run("taxonomy", "--json")
    assert args.func(args) == 0
    rows = json.loads(capsys.readouterr().out)
    ids = [r["id"] for r in rows]
    assert "FM-1.3" in ids and "OTHER" in ids
    assert all({"id", "name", "category", "definition"} <= set(r)
               for r in rows)


def test_explain_json_single_and_table(capsys):
    args = _run("explain", "FM-1.3", "--json")
    assert args.func(args) == 0
    one = json.loads(capsys.readouterr().out)
    assert one["id"] == "FM-1.3"
    assert one["definition"]

    args = _run("explain", "--json")
    assert args.func(args) == 0
    table = json.loads(capsys.readouterr().out)
    assert isinstance(table, list) and len(table) > 10


def test_optimize_json_on_empty_trace(tmp_path, capsys):
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    store = TraceStore(str(tmp_path / "s"))
    rec = Recorder("no facts", save=False)
    rec.respond("done", success=True)
    store.save(rec.trace)
    args = _run("optimize", str(rec.trace.id),
                "--store", str(store.directory), "--json")
    assert args.func(args) == 1
    assert "nothing to optimize" in capsys.readouterr().out


def test_explain_json_includes_fixes_and_detectors(capsys):
    args = _run("explain", "FM-1.3", "--json")
    assert args.func(args) == 0
    one = json.loads(capsys.readouterr().out)
    assert one["fixes"] and isinstance(one["fixes"], list)
    assert any("Repeat" in d for d in one["detectors"])


def test_annotations_verdict_filter(tmp_path, capsys):
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    store = TraceStore(str(tmp_path / "s"))
    rec = Recorder("filter fixture", save=False)
    rec.trace.id = "f-1"
    rec.respond("done", success=True)
    store.save(rec.trace)
    store.annotate("f-1", "real bug", verdict="confirmed")
    store.annotate("f-1", "operator error", verdict="false-positive")
    args = argparse.Namespace(store=str(store.directory), trace=None,
                              json=True, verdict="confirmed")
    assert cmd_annotations(args) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [r["note"] for r in rows] == ["real bug"]
