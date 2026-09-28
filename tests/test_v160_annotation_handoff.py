"""v160: store handoff — the triage story travels with the traces.

`export --with-annotations` writes the triage sidecar next to the
transcript export (OUT.annotations.jsonl); `import --annotations`
merges a sidecar append-only: rows the store has never seen are
added, everything else (including a full re-import of the same file)
is skipped. The evidence chain never hears about it.
"""

import argparse
import json

from approximately.cli import cmd_export, cmd_import
from approximately.exporter import export_annotations
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed_with_notes(directory):
    store = TraceStore(directory)
    rec = Recorder("the failing run", save=False)
    rec.tool("deploy", {"env": "prod"}, result=None, error="timeout")
    rec.respond("gave up", success=False)
    store.save(rec.trace)
    store.annotate(rec.trace.id, "known flake, env issue",
                   author="op", verdict="confirmed")
    return store, rec.trace.id


def test_export_with_annotations_writes_sidecar(tmp_path):
    store, _ = _seed_with_notes(tmp_path / "s")
    out = tmp_path / "handoff.jsonl"
    from approximately.exporter import export_store

    export_store(store, out)
    count = export_annotations(store,
                               tmp_path / "handoff.annotations.jsonl")
    assert count == 1
    rows = [json.loads(line) for line in
            (tmp_path / "handoff.annotations.jsonl")
            .read_text(encoding="utf-8").splitlines()]
    assert rows[0]["note"] == "known flake, env issue"


def test_cli_export_with_annotations(tmp_path, capsys):
    store, _ = _seed_with_notes(tmp_path / "s")
    args = argparse.Namespace(store=str(store.directory),
                              output=str(tmp_path / "out.jsonl"),
                              format="openai-jsonl", query=None,
                              since=None, with_annotations=True,
                              json=True)
    assert cmd_export(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["annotations"] == 1
    assert (tmp_path / "out.annotations.jsonl").is_file()


def _write_sidecar(tmp_path, trace_id):
    sidecar = tmp_path / "notes.jsonl"
    sidecar.write_text(json.dumps({
        "trace_id": trace_id, "note": "known flake, env issue",
        "author": "op", "verdict": "confirmed"}) + "\n",
        encoding="utf-8")
    return sidecar


def test_import_annotations_merges_append_only(tmp_path, capsys):
    fresh = TraceStore(tmp_path / "fresh")
    rec = Recorder("the failing run", save=False)
    rec.tool("deploy", {"env": "prod"}, result=None, error="timeout")
    rec.respond("gave up", success=False)
    fresh.save(rec.trace)
    sidecar = _write_sidecar(tmp_path, rec.trace.id)
    args = argparse.Namespace(store=str(fresh.directory),
                              files=[str(sidecar)], format="auto",
                              dry_run=False, jobs=1,
                              annotations=True, json=True)
    assert cmd_import(args) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["annotations"]["added"] == 1
    # re-import: the whole file is already on file
    assert cmd_import(args) == 0
    again = json.loads(capsys.readouterr().out)
    assert again["annotations"]["added"] == 0
    assert again["annotations"]["skipped"] == 1
    assert len(fresh.annotations()) == 1


def test_import_annotations_skips_garbage(tmp_path, capsys):
    fresh = TraceStore(tmp_path / "fresh")
    sidecar = tmp_path / "messy.jsonl"
    sidecar.write_text('{"trace_id": "abc123", "note": "ok"}\n'
                       "{broken\n", encoding="utf-8")
    args = argparse.Namespace(store=str(fresh.directory),
                              files=[str(sidecar)], format="auto",
                              dry_run=False, jobs=1,
                              annotations=True, json=True)
    assert cmd_import(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["annotations"] == {"added": 1, "skipped": 1}
