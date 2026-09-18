"""v0.41 — store doctor: health check over store + digest history."""

from __future__ import annotations

import argparse
import json
import os
import time

from approximately.cli import cmd_doctor
from approximately.doctor import doctor
from approximately.ledger import EvidenceLedger
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store(tmp_path, n=2, signed=False):
    store = TraceStore(str(tmp_path / "traces"))
    recs = []
    for i in range(n):
        rec = Recorder(f"task {i}", save=False)
        rec.trace.id = f"d-{i}"
        rec.tool("bash", {"cmd": "ls"}, result="ok")
        rec.respond("done", success=True)
        store.save(rec.trace)
        recs.append(rec)
    return store, recs


def test_healthy_store_reports_healthy(tmp_path):
    store, _ = _store(tmp_path)
    report = doctor(store.directory)
    assert report.healthy
    assert report.records == 2
    assert "healthy" in report.render()


def test_corrupt_and_mismatched_files_found(tmp_path):
    store, _ = _store(tmp_path)
    (store.directory / "broken.json").write_text("{not json", encoding="utf-8")
    payload = json.loads((store.directory / "d-0.json").read_text())
    (store.directory / "wrongname.json").write_text(
        json.dumps(payload), encoding="utf-8")
    report = doctor(store.directory)
    assert not report.healthy
    assert "broken.json" in report.corrupt
    assert "wrongname.json" in report.id_mismatch
    assert report.records == 3  # 2 proper + 1 duplicate under wrong name


def test_ledger_tamper_reported(tmp_path):
    store, recs = _store(tmp_path)
    from approximately.integrity import compute_chain

    ledger = EvidenceLedger(store.directory)
    for rec in recs:
        chain = compute_chain(rec.trace)
        ledger.append(rec.trace.id, chain[-1])
    # tamper with the last append by rewriting the ledger's tail entry
    path = store.directory / "ledger.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[-1])
    entry["root"] = "f" * 64  # rewrite history, keep the chain hash
    lines[-1] = json.dumps(entry, sort_keys=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = doctor(store.directory)
    assert report.ledger_present
    assert report.ledger_intact is False
    assert not report.healthy


def test_stale_lock_and_temp_files_found(tmp_path):
    store, _ = _store(tmp_path)
    lock = store.directory / ".d-9.lock"
    lock.write_text("", encoding="utf-8")
    old = time.time() - 7200
    os.utime(lock, (old, old))
    (store.directory / ".d-9.4242.tmp").write_text("partial", encoding="utf-8")
    report = doctor(store.directory)
    assert ".d-9.lock" in report.stale_locks
    assert any(".tmp" in name for name in report.temp_files)
    assert not report.healthy


def test_fresh_lock_not_flagged(tmp_path):
    store, _ = _store(tmp_path)
    lock = store.directory / ".d-9.lock"
    lock.write_text("", encoding="utf-8")
    report = doctor(store.directory)
    assert report.stale_locks == []


def test_digest_gaps_and_torn_lines(tmp_path):
    store, _ = _store(tmp_path)
    digests = tmp_path / "digests"
    digests.mkdir()
    for stamp in ("20260915", "20260917"):  # 16th missing
        (digests / f"digest-{stamp}.jsonl").write_text(
            json.dumps({"ts": 0, "stores": [], "worsening": []}) + "\n"
            + '{"torn"',
            encoding="utf-8")
    report = doctor(store.directory, digest_dir=digests)
    assert report.digest_days == 2
    assert report.digest_gaps == ["20260916"]
    assert report.torn_lines == 2
    assert not report.healthy


def test_cli_doctor_json_exit_codes(tmp_path, capsys):
    store, _ = _store(tmp_path)
    rc = cmd_doctor(argparse.Namespace(
        store=str(store.directory), digest_dir=None, json=True))
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["healthy"] is True and out["records"] == 2

    (store.directory / "bad.json").write_text("nope", encoding="utf-8")
    rc = cmd_doctor(argparse.Namespace(
        store=str(store.directory), digest_dir=None, json=False))
    text = capsys.readouterr().out
    assert rc == 1
    assert "PROBLEMS FOUND" in text and "bad.json" in text
