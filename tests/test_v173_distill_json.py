"""v174: `export-dataset --json` / `distill --json` — stats as data.

Both labeling exporters print prose tallies; `--json` emits the stats
dict (written/labeled/skipped/modes + the judge-cache tally when a
teacher cache was in play) with a `source` field naming the labeler.
"""

import argparse
import json

from approximately.cli import cmd_distill, cmd_export_dataset
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed(directory):
    store = TraceStore(directory)
    rec = Recorder("the failing run", save=False)
    rec.tool("deploy", {"env": "prod"}, result=None, error="timeout")
    rec.respond("gave up", success=False)
    store.save(rec.trace)
    return store


def test_export_dataset_json(tmp_path, capsys):
    store = _seed(tmp_path / "s")
    args = argparse.Namespace(store=str(store.directory),
                              output=str(tmp_path / "ds.jsonl"),
                              teacher=None, teacher_cache=None,
                              dedupe=False, json=True)
    assert cmd_export_dataset(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["written"] == 1
    assert payload["source"] == "rule detectors"
    assert "judge_cache" not in payload


def test_distill_json_carries_modes(tmp_path, capsys):
    store = _seed(tmp_path / "s")
    args = argparse.Namespace(store=str(store.directory),
                              output=str(tmp_path / "sft.jsonl"),
                              teacher=None, teacher_cache=None,
                              dedupe=False, json=True)
    assert cmd_distill(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["source"] == "rule detectors"
    # the rule detectors attribute this timeout to FM-3.1
    assert payload["modes"] == {"FM-3.1": 1}
