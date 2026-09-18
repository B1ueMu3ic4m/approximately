"""v0.49 — doctor --fix: remove stale locks and temp files safely."""

from __future__ import annotations

import argparse
import json
import os
import time

from approximately.cli import cmd_doctor
from approximately.doctor import doctor, fix_hygiene
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store(tmp_path, n=1):
    store = TraceStore(str(tmp_path / "traces"))
    for i in range(n):
        rec = Recorder(f"task {i}", save=False)
        rec.trace.id = f"fx-{i}"
        rec.tool("bash", {"cmd": "ls"}, result="ok")
        rec.respond("done", success=True)
        store.save(rec.trace)
    return store


def _stale_lock(store):
    lock = store.directory / ".fx-0.lock"
    lock.write_text("", encoding="utf-8")
    old = time.time() - 7200
    os.utime(lock, (old, old))
    return lock


def test_fix_removes_stale_lock_and_temp(tmp_path):
    store = _store(tmp_path)
    lock = _stale_lock(store)
    tmp = store.directory / ".fx-0.4242.tmp"
    tmp.write_text("partial", encoding="utf-8")
    report = doctor(store.directory)
    removed = fix_hygiene(store.directory, report)
    assert ".fx-0.lock" in removed and ".fx-0.4242.tmp" in removed
    assert not lock.exists() and not tmp.exists()
    # re-check: store is healthy now
    assert doctor(store.directory).healthy


def test_fix_never_touches_records_or_ledger(tmp_path):
    store = _store(tmp_path, n=2)
    _stale_lock(store)
    ledger = store.directory / "ledger.jsonl"
    ledger.write_text('{"seq": 1}\n', encoding="utf-8")
    report = doctor(store.directory)
    removed = fix_hygiene(store.directory, report)
    assert all(not r.endswith(".json") for r in removed)
    assert ledger.exists()
    assert report.records == 2


def test_fix_via_cli_restores_health(tmp_path, capsys):
    store = _store(tmp_path)
    _stale_lock(store)
    (store.directory / ".x.1.tmp").write_text("t", encoding="utf-8")
    args = argparse.Namespace(store=str(store.directory),
                              digest_dir=None, json=False, fix=True)
    rc = cmd_doctor(args)
    captured = capsys.readouterr()
    assert rc == 0  # hygiene findings cleared -> healthy verdict
    assert "removed 2 hygiene artifact(s)" in captured.err
    assert "healthy" in captured.out


def test_fix_preserves_fresh_lock(tmp_path):
    store = _store(tmp_path)
    fresh = store.directory / ".fx-9.lock"
    fresh.write_text("", encoding="utf-8")  # young lock: keep it
    report = doctor(store.directory)
    removed = fix_hygiene(store.directory, report)
    assert removed == []
    assert fresh.exists()


def test_cli_doctor_json_fix_payload(tmp_path, capsys):
    store = _store(tmp_path)
    _stale_lock(store)
    args = argparse.Namespace(store=str(store.directory),
                              digest_dir=None, json=True, fix=True)
    cmd_doctor(args)
    payload = json.loads(capsys.readouterr().out)
    assert payload["stale_locks"] == []
    assert payload["healthy"] is True
