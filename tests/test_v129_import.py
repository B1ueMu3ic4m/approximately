"""v1.19.0 — batch import of foreign transcript JSONL."""

import argparse
import json

import pytest

from approximately.cli import cmd_import
from approximately.importer import import_file, sniff_format
from approximately.store import TraceStore
from approximately.trace import MESSAGE, OBSERVATION, RESPONSE


@pytest.fixture()
def store(tmp_path):
    return TraceStore(tmp_path / "store")


def _write(tmp_path, name, lines):
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n",
                   encoding="utf-8")
    return path


def test_sniff_shapes(tmp_path):
    native = _write(tmp_path, "native.jsonl", [
        {"id": "abc123", "task": "t", "steps": []}])
    openai = _write(tmp_path, "openai.jsonl", [
        {"messages": [{"role": "user", "content": "hi"}]}])
    bare = _write(tmp_path, "bare.jsonl", [
        [{"role": "user", "content": "hi"}]])
    assert sniff_format(native) == "native"
    assert sniff_format(openai) == "openai-jsonl"
    assert sniff_format(bare) == "messages-list"


def test_import_openai_jsonl_with_tool_error(store, tmp_path):
    path = _write(tmp_path, "runs.jsonl", [
        {"messages": [
            {"role": "user", "content": "list the files"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"function": {"name": "ls",
                              "arguments": "{\"path\": \"/tmp\"}"}}]},
            {"role": "tool", "name": "ls", "content": "boom",
             "is_error": True},
        ]},
        {"messages": [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]},
    ])
    result = import_file(path, store)
    assert result["format"] == "openai-jsonl"
    assert result["imported"] == 2 and result["skipped"] == 0
    failed = [store.load(tid) for tid in result["trace_ids"]]
    by_task = {t.task: t for t in failed}
    crashed = by_task["list the files"]
    assert crashed.success is False
    kinds = [s.kind for s in crashed.steps]
    assert "tool_call" in kinds and kinds.count(RESPONSE) == 0
    obs = next(s for s in crashed.steps if s.kind == OBSERVATION)
    assert obs.error and obs.tool == "ls"
    ok = by_task["hello"]
    assert ok.success is True
    assert ok.steps[0].kind == MESSAGE
    assert ok.steps[1].kind == RESPONSE


def test_reimport_is_idempotent(store, tmp_path):
    path = _write(tmp_path, "runs.jsonl", [
        {"messages": [{"role": "user", "content": "hi"},
                      {"role": "assistant", "content": "yo"}]}])
    first = import_file(path, store)
    assert first["imported"] == 1
    again = import_file(path, store)
    assert again["imported"] == 0 and again["skipped"] == 1
    assert len(store.list_traces()) == 1


def test_native_import_keeps_ids_and_chain(tmp_path, store):
    from approximately.integrity import verify
    from approximately.recorder import Recorder

    rec = Recorder("native run", save=False)
    rec.tool("ls", {"path": "/"}, "files")
    rec.respond("done", success=True)
    saved = rec.trace
    path = _write(tmp_path, "native.jsonl", [saved.to_dict()])
    result = import_file(path, store)
    assert result["imported"] == 1
    loaded = store.load(saved.id)
    assert loaded is not None and loaded.task == "native run"
    assert verify(loaded).verdict in ("intact", "unsigned")


def test_malformed_lines_are_skipped_not_fatal(store, tmp_path):
    path = tmp_path / "messy.jsonl"
    path.write_text(
        json.dumps({"messages": [{"role": "user", "content": "ok"}]})
        + "\nnot json at all\n[1, 2, 3]\n{}\n",
        encoding="utf-8")
    result = import_file(path, store)
    assert result["lines"] == 4
    assert result["imported"] == 1
    assert result["skipped"] == 3


def test_dry_run_writes_nothing(store, tmp_path):
    path = _write(tmp_path, "runs.jsonl", [
        {"messages": [{"role": "user", "content": "hi"},
                      {"role": "assistant", "content": "yo"}]}])
    result = import_file(path, store, dry_run=True)
    assert result["imported"] == 1
    assert store.list_traces() == []


def test_cli_import_json(tmp_path, capsys):
    store_dir = tmp_path / "store"
    path = _write(tmp_path, "runs.jsonl", [
        {"messages": [{"role": "user", "content": "q"},
                      {"role": "assistant", "content": "a"}]}])
    args = argparse.Namespace(store=str(store_dir), file=str(path),
                              format="auto", dry_run=False, json=True)
    assert cmd_import(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["imported"] == 1
    assert TraceStore(store_dir).load(payload["trace_ids"][0])


def test_cli_import_rejects_unknown_shape(tmp_path, capsys):
    path = tmp_path / "odd.jsonl"
    path.write_text('{"foo": 1}\n', encoding="utf-8")
    args = argparse.Namespace(store=str(tmp_path / "store"),
                              file=str(path), format="auto",
                              dry_run=False, json=False)
    assert cmd_import(args) == 2
    assert "unrecognized" in capsys.readouterr().err
