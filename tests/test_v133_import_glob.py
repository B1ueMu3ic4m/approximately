"""v133: import at scale — multiple files and glob patterns.

`approximately import` accepts several arguments now; glob patterns
expand (sorted, deduplicated) and the JSON payload carries per-file
counts so operators can see which log files pulled their weight.
"""

import argparse
import json

from approximately.cli import cmd_import
from approximately.importer import _expand, import_paths
from approximately.store import TraceStore


def _line(task):
    return json.dumps({"messages": [
        {"role": "user", "content": task},
        {"role": "assistant", "content": "ok"}]})


def _write(tmp_path, name, task):
    path = tmp_path / name
    path.write_text(_line(task) + "\n", encoding="utf-8")
    return path


def test_expand_sorted_and_deduplicated(tmp_path):
    _write(tmp_path, "b.jsonl", "b")
    _write(tmp_path, "a.jsonl", "a")
    files = _expand([str(tmp_path / "*.jsonl"),
                     str(tmp_path / "a.jsonl")])
    names = [f.name for f in files]
    assert names == ["a.jsonl", "b.jsonl"]


def test_multi_file_aggregate_and_per_file(tmp_path):
    _write(tmp_path, "a.jsonl", "alpha")
    _write(tmp_path, "b.jsonl", "beta")
    store = TraceStore(tmp_path / "s")
    result = import_paths([str(tmp_path / "a.jsonl"),
                           str(tmp_path / "b.jsonl")], store)
    assert result["files"] == 2
    assert result["imported"] == 2 and result["skipped"] == 0
    assert [row["file"] for row in result["per_file"]] == [
        str(tmp_path / "a.jsonl"), str(tmp_path / "b.jsonl")]
    assert len(store.list_traces()) == 2


def test_identical_transcripts_dedupe_across_files(tmp_path):
    _write(tmp_path, "a.jsonl", "same")
    _write(tmp_path, "b.jsonl", "same")
    store = TraceStore(tmp_path / "s")
    result = import_paths([str(tmp_path / "*.jsonl")], store)
    # deterministic ids: the same transcript in two log files is one
    # trace, not a duplicate
    assert result["imported"] == 1
    assert len(store.list_traces()) == 1
    again = import_paths([str(tmp_path / "*.jsonl")], store)
    assert again["imported"] == 0 and again["skipped"] == 2


def test_no_match_is_valueerror(tmp_path):
    import pytest

    store = TraceStore(tmp_path / "s")
    with pytest.raises(ValueError):
        import_paths([str(tmp_path / "nope-*.jsonl")], store)


def test_cli_multi_file_json_and_dry_run(tmp_path, capsys):
    _write(tmp_path, "a.jsonl", "alpha")
    _write(tmp_path, "b.jsonl", "beta")
    args = argparse.Namespace(store=str(tmp_path / "s"),
                              files=[str(tmp_path / "a.jsonl"),
                                     str(tmp_path / "b.jsonl")],
                              format="auto", dry_run=True, json=True)
    assert cmd_import(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["imported"] == 2 and payload["files"] == 2
    assert TraceStore(tmp_path / "s").list_traces() == []


def test_cli_missing_everything_exits_two(tmp_path, capsys):
    args = argparse.Namespace(store=str(tmp_path / "s"),
                              files=[str(tmp_path / "ghost.jsonl")],
                              format="auto", dry_run=False, json=False)
    assert cmd_import(args) == 2
    assert "no files matched" in capsys.readouterr().err


def test_import_directory_arg(tmp_path):
    for i in range(3):
        (tmp_path / f"run-{i}.jsonl").write_text(
            json.dumps({"messages": [
                {"role": "user", "content": f"task {i}"},
                {"role": "assistant", "content": "ok"}]}) + "\n",
            encoding="utf-8")
    (tmp_path / "notes.txt").write_text("not a transcript\n",
                                        encoding="utf-8")
    store = TraceStore(tmp_path / "s")
    result = import_paths([str(tmp_path)], store)
    assert result["files"] == 3
    assert result["imported"] == 3
