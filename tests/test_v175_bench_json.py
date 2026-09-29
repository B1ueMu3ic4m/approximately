"""v175: `benchmark --json` / `convert-mast --json` — the last tallies.

The benchmark result (accuracy, macro-F1, per-mode CIs) and the
MAST-Data conversion stats become data — the `--json` sweep is now
complete across every command that prints numbers.
"""

import argparse
import json

from approximately.cli import cmd_benchmark, cmd_convert_mast


def test_benchmark_json(tmp_path, capsys):
    args = argparse.Namespace(
        dataset="docs/mast-bench-multi.jsonl", format="approx",
        judge=False, judge_cache=None, judge_model=None,
        multi_label=True, html=None, json=True)
    assert cmd_benchmark(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["records"] > 0
    # the multi-label path carries sample metrics, not accuracy
    assert "sample_precision" in payload
    assert 0.0 <= payload["sample_precision"] <= 1.0
    assert 0.0 <= payload["macro_f1"] <= 1.0
    assert payload["source"].startswith("rule detectors")
    for spec in payload["per_mode"].values():
        assert "precision_ci" in spec


def test_convert_mast_json(tmp_path, capsys):
    source = "docs/mast-bench-multi.jsonl"
    out = tmp_path / "mast.jsonl"
    args = argparse.Namespace(source=source, output=str(out),
                              multi_label=True, json=True)
    rc = cmd_convert_mast(args)
    payload = json.loads(capsys.readouterr().out)
    assert payload["output"] == str(out)
    assert isinstance(payload["labels"], dict)
    assert rc == (0 if payload["converted"] else 1)
