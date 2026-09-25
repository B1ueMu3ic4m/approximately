"""v115: `bench-gate --json` and `merge --json` — the last CI-facing
prose-only commands join the machine-readable story.

`bench-gate --json` emits the structured gate_result (exit 1 on any
violation); `merge --json` emits the merge report including the
annotation sidecar count. Text output unchanged.
"""

import argparse
import json
from pathlib import Path

from approximately.cli import cmd_merge
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store(tmp_path, name, tid):
    store = TraceStore(str(tmp_path / name))
    rec = Recorder("json fixture", save=False)
    rec.trace.id = tid
    rec.respond("done", success=True)
    store.save(rec.trace)
    return store


def test_bench_gate_json_pass(tmp_path, capsys):
    from approximately.cli import build_parser

    root = Path(__file__).resolve().parents[1]
    args = build_parser().parse_args([
        "bench-gate", str(root / "docs" / "mast-bench-multi.jsonl"),
        "--floors", str(root / "docs" / "bench-floors.json"), "--json",
    ])
    assert args.func(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is True
    assert "sample_f1" in payload and "modes" in payload


def test_bench_gate_json_fail_exits_one(tmp_path, capsys):
    from approximately.cli import build_parser

    floors = tmp_path / "impossible.json"
    floors.write_text(json.dumps({"sample_f1": 1.01}), encoding="utf-8")
    root = Path(__file__).resolve().parents[1]
    args = build_parser().parse_args([
        "bench-gate", str(root / "docs" / "mast-bench-multi.jsonl"),
        "--floors", str(floors), "--json",
    ])
    assert args.func(args) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is False
    assert payload["violations"]


def test_merge_json_report(tmp_path, capsys):
    source = _store(tmp_path, "src", "m-1")
    target = _store(tmp_path, "dst", "m-2")
    source.annotate("m-1", "note rides along")
    args = argparse.Namespace(store=str(target.directory),
                              source=str(source.directory),
                              on_conflict="skip", json=True)
    assert cmd_merge(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["imported"] == ["m-1"]
    assert payload["annotations_carried"] == 1


def test_merge_text_unchanged(tmp_path, capsys):
    from approximately.cli import build_parser

    source = _store(tmp_path, "src", "m-1")
    target = _store(tmp_path, "dst", "m-2")
    args = build_parser().parse_args([
        "merge", str(source.directory), "--store",
        str(target.directory),
    ])
    assert args.func(args) == 0
    out = capsys.readouterr().out
    assert not out.lstrip().startswith("{")
