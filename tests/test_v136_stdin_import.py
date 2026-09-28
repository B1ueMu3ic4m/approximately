"""v136: `import -` reads transcripts from stdin.

Piping is the agent-native path: `other_tool dumps | approximately
import - --store s` lands runs in the tamper-evident store without a
temp file. Same sniffing, idempotence and skip-counting as files.
"""

import argparse
import io
import json

import pytest

from approximately.cli import cmd_import
from approximately.importer import import_lines, import_paths
from approximately.store import TraceStore


def _line(task):
    return json.dumps({"messages": [
        {"role": "user", "content": task},
        {"role": "assistant", "content": "ok"}]})


def test_import_lines_from_stream(tmp_path):
    store = TraceStore(tmp_path / "s")
    result = import_lines([_line("piped"), "", "{broken"],
                          store)
    assert result["imported"] == 1
    assert result["skipped"] == 1
    assert result["lines"] == 2
    assert len(store.list_traces()) == 1


def test_import_paths_stdin_mixed_with_files(tmp_path, monkeypatch):
    path = tmp_path / "a.jsonl"
    path.write_text(_line("from file") + "\n", encoding="utf-8")
    monkeypatch.setattr("sys.stdin", io.StringIO(_line("piped") + "\n"))
    store = TraceStore(tmp_path / "s")
    result = import_paths(["-", str(path)], store)
    assert result["files"] == 2
    assert result["imported"] == 2
    assert result["per_file"][0]["file"] == "<stdin>"
    assert len(store.list_traces()) == 2


def test_empty_stdin_is_documented_error(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    store = TraceStore(tmp_path / "s")
    with pytest.raises(ValueError):
        import_paths(["-"], store)


def test_cli_stdin_import(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin",
                        io.StringIO(_line("cli pipe") + "\n"))
    args = argparse.Namespace(store=str(tmp_path / "s"), files=["-"],
                              format="auto", dry_run=False, json=True)
    assert cmd_import(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["imported"] == 1
    assert TraceStore(tmp_path / "s").load(payload["trace_ids"][0])


def test_import_lines_accepts_one_pass_stream(tmp_path):
    # a generator (like real stdin): the sniffed first line must be
    # re-joined, not lost, and nothing may be processed twice
    store = TraceStore(tmp_path / "s")
    stream = iter([_line("first via stream"), "",
                   "{broken"])
    result = import_lines(stream, store)
    assert result["imported"] == 1
    assert result["skipped"] == 1
    assert len(store.list_traces()) == 1
