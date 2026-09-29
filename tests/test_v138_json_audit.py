"""v138: the ops seven learn --json.

The all-commands-`--json` rule (v1.18) was aspirational on seven
operators' commands; this closes the gap for the ones scripts and MCP
mirrors actually call: annotate, anomalies, metrics, clean, repair,
rotate, scan-tool. Prose stays the default; JSON is additive.
"""

import argparse
import json

from approximately.cli import (
    cmd_annotate,
    cmd_anomalies,
    cmd_clean,
    cmd_metrics,
    cmd_repair,
    cmd_rotate,
    cmd_scan_tool,
)
from approximately.integrity import sign
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _slow_trace(directory):
    store = TraceStore(directory)
    rec = Recorder("slow run", save=False)
    for _ in range(5):
        rec.tool("deploy", {"env": "prod"}, result="ok")
    rec.respond("done", success=True)
    # the Recorder auto-times; stamp the window by hand for the test
    for step, ms in zip(rec.trace.steps, (5, 6, 5, 6, 9000)):
        step.latency_ms = ms
    store.save(rec.trace)
    return rec.trace, store


def test_annotate_json(tmp_path, capsys):
    store = TraceStore(tmp_path / "s")
    rec = Recorder("t", save=False)
    rec.respond("done", success=True)
    store.save(rec.trace)
    args = argparse.Namespace(store=str(store.directory),
                              trace=rec.trace.id, note="checked",
                              author="op", verdict="confirmed",
                              json=True)
    assert cmd_annotate(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["annotated"] is True
    assert payload["notes_on_file"] == 1
    assert payload["entry"]["note"] == "checked"


def test_anomalies_json(tmp_path, capsys):
    trace, store = _slow_trace(tmp_path / "s")
    args = argparse.Namespace(store=str(store.directory),
                              trace=trace.id, threshold=3.5, json=True)
    rc = cmd_anomalies(args)
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, list) and payload
    assert payload[0]["direction"] in ("slow", "fast")
    assert "robust_z" in payload[0]
    assert rc == 1


def test_metrics_json_store_and_prometheus(tmp_path, capsys):
    _slow_trace(tmp_path / "s")
    store_dir = str(tmp_path / "s")
    args = argparse.Namespace(store=store_dir, prometheus=False,
                              by_agent=False, by_tool=False,
                              label=None, json=True)
    assert cmd_metrics(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["traces"] == 1
    args = argparse.Namespace(store=store_dir, prometheus=True,
                              by_agent=False, by_tool=False,
                              label=None, json=True)
    assert cmd_metrics(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["format"] == "prometheus"
    assert "approximately_" in payload["text"]


def test_clean_json(tmp_path, capsys):
    import os
    import time

    trace, store = _slow_trace(tmp_path / "s")
    # clean gates on file mtime; backdate it directly so keep_days=0
    # never races the clock (created_at is not what clean reads)
    old = time.time() - 86400
    os.utime(store.directory / f"{trace.id}.json", (old, old))
    args = argparse.Namespace(store=str(store.directory),
                              keep_days=0, json=True)
    assert cmd_clean(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["removed"] == 1 and payload["keep_days"] == 0


def test_repair_json(tmp_path, capsys):
    trace, store = _slow_trace(tmp_path / "s")
    args = argparse.Namespace(store=str(store.directory),
                              trace=trace.id, apply=False, json=True)
    assert cmd_repair(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "cleared_modes" in payload and "repaired" in payload
    assert payload["written"] is None


def _signed_store(tmp_path):
    store = TraceStore(str(tmp_path / "traces"))
    rec = Recorder("signed", save=False)
    rec.tool("bash", {"cmd": "ls"}, result="ok")
    rec.respond("done", success=True)
    sign(rec.trace)
    store.save(rec.trace)
    return rec, store


def test_rotate_json_success_and_refusal(tmp_path, capsys):
    rec_obj, store = _signed_store(tmp_path)
    rec = rec_obj.trace
    new_key = tmp_path / "new.key"
    new_key.write_bytes(b"brand-new-key")
    args = argparse.Namespace(store=str(store.directory),
                              trace=rec.id, old_key_file=None,
                              new_key_file=str(new_key), json=True)
    assert cmd_rotate(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"rotated": True, "trace_id": rec.id}

    args = argparse.Namespace(store=str(store.directory),
                              trace=rec.id, old_key_file=None,
                              new_key_file=None, json=True)
    with __import__("pytest").raises(SystemExit, match="new-key-file"):
        cmd_rotate(args)


def test_scan_tool_json(tmp_path, capsys):
    path = tmp_path / "tool.md"
    path.write_text("# ls tool\nRuns `ls` on the host.\n",
                    encoding="utf-8")
    args = argparse.Namespace(store=str(tmp_path), file=str(path),
                              json=True)
    rc = cmd_scan_tool(args)
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] in ("clean", "suspicious", "malicious")
    assert isinstance(payload["findings"], list)
    assert rc == (0 if payload["verdict"] == "clean" else 1)
