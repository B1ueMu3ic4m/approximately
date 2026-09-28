"""v168: `export --dedupe` — the sharing side learns the same trick.

`distill --dedupe` protects training data; `export --dedupe`
(CLI + MCP `dedupe` param) protects everything else you hand to a
colleague: retries and cron double-fires leave the export before
they can waste anyone's attention.
"""

import argparse
import json

from approximately.cli import cmd_export
from approximately.exporter import export_store
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed_with_twins(directory):
    store = TraceStore(directory)
    for _ in range(2):
        rec = Recorder("book a flight to Oslo", save=False)
        rec.tool("search", {"q": "oslo flights"}, result="3 hits")
        rec.respond("booked", success=True)
        store.save(rec.trace)
    rec = Recorder("water the plants", save=False)
    rec.respond("done", success=True)
    store.save(rec.trace)
    return store


def test_export_dedupe_drops_twins(tmp_path):
    store = _seed_with_twins(tmp_path / "s")
    out = tmp_path / "out.jsonl"
    result = export_store(store, out, dedupe=True)
    assert result["written"] == 2
    assert result["dedupe_dropped"] == 1
    rows = [json.loads(line) for line in
            out.read_text(encoding="utf-8").splitlines()]
    tasks = sorted(r["metadata"]["task"] for r in rows)
    assert tasks == ["book a flight to Oslo", "water the plants"]


def test_export_without_dedupe_keeps_all(tmp_path):
    store = _seed_with_twins(tmp_path / "s")
    out = tmp_path / "out.jsonl"
    result = export_store(store, out)
    assert result["written"] == 3
    assert result["dedupe_dropped"] == 0


def test_cli_export_dedupe(tmp_path, capsys):
    store = _seed_with_twins(tmp_path / "s")
    args = argparse.Namespace(store=str(store.directory),
                              output=str(tmp_path / "out.jsonl"),
                              format="openai-jsonl", query=None,
                              since=None, with_annotations=False,
                              dedupe=True, json=True)
    assert cmd_export(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["written"] == 2
    assert payload["dedupe_dropped"] == 1
