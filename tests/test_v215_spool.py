"""v215: `spool` — the directory that feeds the store.

Agents, cron exports and webhook receivers drop transcript/OTLP
files somewhere; spool turns that somewhere into a continuously
ingested store.  Contract: parse-able files always move aside,
unparseable files always stay (nothing lost silently), re-delivery
is a no-op (deterministic ids), and a failed trace in the batch is
a gateable exit code.
"""

import argparse
import json

from approximately.cli import cmd_spool
from approximately.exporter import export_store
from approximately.recorder import Recorder
from approximately.spool import spool_pass, watch_spool
from approximately.store import TraceStore


def _transcript_file(path, task="spooled run", success=True):
    rec = Recorder(task, save=False)
    rec.tool("shell", {"cmd": "ls"}, result="ok")
    rec.respond("done", success=success)
    path.write_text(json.dumps(rec.trace.to_dict()) + "\n",
                    encoding="utf-8")
    return path


def test_pass_ingests_and_archives(tmp_path):
    store = TraceStore(tmp_path / "s")
    spool = tmp_path / "spool"
    spool.mkdir()
    _transcript_file(spool / "a.jsonl")
    _transcript_file(spool / "b.jsonl", task="second run")
    result = spool_pass(store, spool)
    assert result["files"] == 2
    assert result["imported"] == 2
    assert result["archived"] == 2
    assert result["left"] == 0
    assert len(list(spool.glob("*.jsonl"))) == 0
    assert len(list((spool / "done").glob("*"))) == 2
    assert len(store.list_traces()) == 2


def test_unparseable_file_stays_put(tmp_path):
    store = TraceStore(tmp_path / "s")
    spool = tmp_path / "spool"
    spool.mkdir()
    (spool / "junk.json").write_text("{ not json", encoding="utf-8")
    _transcript_file(spool / "good.jsonl")
    result = spool_pass(store, spool)
    assert result["failures"] == 1
    assert result["left"] == 1
    assert (spool / "junk.json").exists()
    assert not (spool / "good.jsonl").exists()
    assert len(store.list_traces()) == 1


def test_redelivery_is_a_noop_but_still_archives(tmp_path):
    store = TraceStore(tmp_path / "s")
    spool = tmp_path / "spool"
    spool.mkdir()
    import shutil

    source = _transcript_file(tmp_path / "source.jsonl")
    # first delivery
    shutil.copy(source, spool / "a.jsonl")
    result = spool_pass(store, spool)
    assert result["imported"] == 1
    # the same bytes land again (at-least-once delivery)
    shutil.copy(source, spool / "a.jsonl")
    again = spool_pass(store, spool)
    assert again["imported"] == 0
    assert again["archived"] == 1      # moves aside anyway
    assert len(store.list_traces()) == 1


def test_delete_mode(tmp_path):
    store = TraceStore(tmp_path / "s")
    spool = tmp_path / "spool"
    spool.mkdir()
    _transcript_file(spool / "a.jsonl")
    result = spool_pass(store, spool, delete=True)
    assert result["deleted"] == 1
    assert not (spool / "a.jsonl").exists()
    assert not (spool / "done").exists()


def test_dry_run_touches_nothing(tmp_path):
    store = TraceStore(tmp_path / "s")
    spool = tmp_path / "spool"
    spool.mkdir()
    _transcript_file(spool / "a.jsonl")
    result = spool_pass(store, spool, dry_run=True)
    assert result["imported"] >= 0
    assert (spool / "a.jsonl").exists()
    assert len(store.list_traces()) == 0


def test_failed_trace_ingestion_sets_gate(tmp_path):
    store = TraceStore(tmp_path / "s")
    spool = tmp_path / "spool"
    spool.mkdir()
    _transcript_file(spool / "bad.jsonl", success=False)
    code = watch_spool(store, spool, once=True, max_passes=1)
    assert code == 1


def test_clean_pass_exits_zero(tmp_path):
    store = TraceStore(tmp_path / "s")
    spool = tmp_path / "spool"
    spool.mkdir()
    _transcript_file(spool / "ok.jsonl", success=True)
    code = watch_spool(store, spool, once=True, max_passes=1)
    assert code == 0


def test_otel_files_spool_through(tmp_path):
    store = TraceStore(tmp_path / "s")
    source = TraceStore(tmp_path / "src")
    rec = Recorder("otel spooled", save=False)
    rec.respond("done", success=True)
    source.save(rec.trace)
    spool = tmp_path / "spool"
    spool.mkdir()
    export_store(source, spool / "run.otlp.json", fmt="otel")
    result = spool_pass(store, spool)
    assert result["imported"] == 1
    assert (spool / "done" / "run.otlp.json").exists()
    assert len(store.list_traces()) == 1


def test_missing_directory_is_loud(tmp_path):
    try:
        spool_pass(TraceStore(tmp_path / "s"), tmp_path / "nope")
    except ValueError as exc:
        assert "spool directory" in str(exc)
    else:
        raise AssertionError("missing directory accepted")


def test_cli_spool_once(tmp_path, capsys):
    store_dir = tmp_path / "s"
    spool = tmp_path / "spool"
    spool.mkdir()
    _transcript_file(spool / "a.jsonl", success=False)
    args = argparse.Namespace(store=str(store_dir), dir=str(spool),
                              interval=1.0, once=True, delete=False,
                              dry_run=False, max_passes=1, json=False)
    assert cmd_spool(args) == 1
    out = capsys.readouterr().out
    assert "spool pass 1" in out
    assert len(TraceStore(store_dir).list_traces()) == 1


def test_pass_reports_failure_modes(tmp_path):
    # ingest-time attribution: the pass says WHAT landed
    store = TraceStore(tmp_path / "s")
    spool = tmp_path / "spool"
    spool.mkdir()
    rec = Recorder("looping run", save=False)
    for _ in range(6):
        rec.tool("search", {"q": "same"}, result="same")
    rec.respond("gave up", success=False)
    (spool / "loop.jsonl").write_text(
        json.dumps(rec.trace.to_dict()) + "\n", encoding="utf-8")
    result = spool_pass(store, spool)
    assert result["failed_traces"] == 1
    assert result["failure_modes"]
    mode = next(iter(result["failure_modes"]))
    assert mode != "OTHER"


def test_watch_line_mentions_modes(tmp_path, capsys):
    store = TraceStore(tmp_path / "s")
    spool = tmp_path / "spool"
    spool.mkdir()
    rec = Recorder("looping run", save=False)
    for _ in range(6):
        rec.tool("search", {"q": "same"}, result="same")
    rec.respond("gave up", success=False)
    (spool / "loop.jsonl").write_text(
        json.dumps(rec.trace.to_dict()) + "\n", encoding="utf-8")
    code = watch_spool(store, spool, once=True, max_passes=1)
    assert code == 1
    out = capsys.readouterr().out
    assert "failures:" in out


def test_json_pass_lines(tmp_path, capsys):
    store_dir = tmp_path / "s"
    spool = tmp_path / "spool"
    spool.mkdir()
    _transcript_file(spool / "a.jsonl", success=False)
    args = argparse.Namespace(store=str(store_dir), dir=str(spool),
                              interval=1.0, once=True, delete=False,
                              dry_run=False, max_passes=1, json=True)
    assert cmd_spool(args) == 1
    import json as _json

    rows = [_json.loads(line) for line in
            capsys.readouterr().out.strip().splitlines()]
    assert len(rows) == 1
    assert rows[0]["pass"] == 1
    assert rows[0]["imported"] == 1
    assert rows[0]["failed_traces"] == 1
