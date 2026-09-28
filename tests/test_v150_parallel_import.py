"""v150: parallel ingest — `import --jobs N`.

A directory of two hundred log files should not take two hundred
times one file. `--jobs N` imports on a thread pool; store saves are
atomic and lock-serialized, so the parallel path is safe, and the
aggregate + per-file counts stay in input order whatever the
completion order was.
"""

import argparse
import json

from approximately.cli import cmd_import
from approximately.importer import import_paths
from approximately.store import TraceStore


def _line(task):
    return json.dumps({"messages": [
        {"role": "user", "content": task},
        {"role": "assistant", "content": "ok"}]})


def _seed_dir(directory, n):
    directory.mkdir(parents=True, exist_ok=True)
    tmp_path = directory
    for i in range(n):
        path = tmp_path / f"log-{i:03d}.jsonl"
        path.write_text(_line(f"task {i}") + "\n", encoding="utf-8")
    return tmp_path


def test_parallel_matches_sequential(tmp_path):
    _seed_dir(tmp_path / "logs", 20)
    fast = TraceStore(tmp_path / "fast")
    result = import_paths([str(tmp_path / "logs" / "*.jsonl")], fast,
                          jobs=6)
    assert result["files"] == 20 and result["imported"] == 20
    assert [row["file"] for row in result["per_file"]] == \
        sorted(row["file"] for row in result["per_file"])
    slow = TraceStore(tmp_path / "slow")
    serial = import_paths([str(tmp_path / "logs" / "*.jsonl")], slow,
                          jobs=1)
    assert serial["trace_ids"] == result["trace_ids"]
    assert len(fast.list_traces()) == len(slow.list_traces()) == 20


def test_parallel_with_corrupt_file_in_the_mix(tmp_path):
    _seed_dir(tmp_path / "logs", 10)
    (tmp_path / "logs" / "log-005.jsonl").write_text(
        "not json\n", encoding="utf-8")
    store = TraceStore(tmp_path / "s")
    result = import_paths([str(tmp_path / "logs" / "*.jsonl")], store,
                          jobs=4)
    assert result["files"] == 10
    assert result["imported"] == 9
    assert result["errors"] == 1
    error_rows = [row for row in result["per_file"]
                  if "error" in row]
    assert len(error_rows) == 1
    assert "log-005" in error_rows[0]["file"]


def test_dry_run_parallel_writes_nothing(tmp_path):
    _seed_dir(tmp_path / "logs", 8)
    store = TraceStore(tmp_path / "s")
    result = import_paths([str(tmp_path / "logs" / "*.jsonl")], store,
                          jobs=4, dry_run=True)
    assert result["imported"] == 8
    assert store.list_traces() == []


def test_cli_import_jobs(tmp_path, capsys):
    _seed_dir(tmp_path / "logs", 6)
    args = argparse.Namespace(store=str(tmp_path / "s"),
                              files=[str(tmp_path / "logs" /
                                         "*.jsonl")],
                              format="auto", dry_run=False,
                              jobs=3, json=True)
    assert cmd_import(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["imported"] == 6 and payload["files"] == 6
