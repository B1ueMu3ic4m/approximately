"""v156: the distill pipeline learns to dedupe.

`export-dataset --dedupe` and `distill --dedupe` drop near-duplicate
traces before labeling: retries and cron double-fires otherwise get
labeled, exported, and trained on as if they were independent
evidence.
"""

import argparse
import json

from approximately.cli import cmd_distill, cmd_export_dataset
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed_with_twins(directory, twins=2, distinct=1):
    store = TraceStore(directory)
    for _ in range(twins):
        rec = Recorder("book a flight to Oslo", save=False)
        rec.tool("search", {"q": "oslo flights"}, result="3 hits")
        rec.respond("booked", success=False)
        store.save(rec.trace)
    for i in range(distinct):
        rec = Recorder(f"water the plants {i}", save=False)
        rec.respond("done", success=True)
        store.save(rec.trace)
    return store


def test_export_dataset_dedupe_drops_twins(tmp_path, capsys):
    store = _seed_with_twins(tmp_path / "s")
    out = tmp_path / "ds.jsonl"
    args = argparse.Namespace(store=str(store.directory),
                              output=str(out), teacher=None,
                              teacher_cache=None, dedupe=True,
                              json=False)
    assert cmd_export_dataset(args) == 0
    out_text = capsys.readouterr().out
    assert "dedupe: dropped 1 near-duplicate trace(s)" in out_text
    rows = [json.loads(line) for line in
            out.read_text(encoding="utf-8").splitlines()]
    # twins are one evidence (the calm run gets no rule label)
    assert len(rows) == 1


def test_export_dataset_without_dedupe_keeps_twins(tmp_path, capsys):
    store = _seed_with_twins(tmp_path / "s")
    out = tmp_path / "ds.jsonl"
    args = argparse.Namespace(store=str(store.directory),
                              output=str(out), teacher=None,
                              teacher_cache=None, dedupe=False,
                              json=False)
    assert cmd_export_dataset(args) == 0
    capsys.readouterr()
    rows = [json.loads(line) for line in
            out.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2


def test_distill_dedupe_flag(tmp_path, capsys):
    store = _seed_with_twins(tmp_path / "s")
    out = tmp_path / "sft.jsonl"
    args = argparse.Namespace(store=str(store.directory),
                              output=str(out), teacher=None,
                              teacher_cache=None, dedupe=True,
                              json=False)
    assert cmd_distill(args) == 0
    out_text = capsys.readouterr().out
    assert "dedupe: dropped 1" in out_text
