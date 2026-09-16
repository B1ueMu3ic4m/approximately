"""v0.11: evidence ledger — self-chained root history, rollback detection."""

from __future__ import annotations

import json

import pytest

from approximately.integrity import sign
from approximately.ledger import (
    EvidenceLedger,
    audit_rollback,
    ledger_path,
    verify_ledger,
)
from approximately.recorder import Recorder
from approximately.store import TraceStore


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("APPROXIMATELY_LEDGER", "1")
    return TraceStore(tmp_path / "store")


def _signed_trace(store, task="ledger task"):
    rec = Recorder(task, store=store, save=False)
    rec.tool("search", {"q": "x"}, result="ok")
    rec.respond("done")
    sign(rec.trace)
    store.save(rec.trace)
    return rec.trace


class TestLedgerBasics:
    def test_append_and_history(self, tmp_path):
        ledger = EvidenceLedger(tmp_path)
        ledger.append("t1", "root-a")
        ledger.append("t1", "root-b")
        ledger.append("t2", "root-c")
        assert [e.root for e in ledger.history("t1")] == ["root-a", "root-b"]
        assert ledger.latest_root("t1") == "root-b"
        assert ledger.latest_root("t2") == "root-c"
        assert ledger.latest_root("t3") is None

    def test_seq_and_chain_linked(self, tmp_path):
        ledger = EvidenceLedger(tmp_path)
        for i in range(5):
            ledger.append(f"t{i % 2}", f"root-{i}")
        entries = ledger.entries()
        assert [e.seq for e in entries] == [1, 2, 3, 4, 5]
        assert verify_ledger(tmp_path).intact
        assert verify_ledger(tmp_path).detail == "5 entries verified"

    def test_empty_ledger(self, tmp_path):
        check = verify_ledger(tmp_path)
        assert check.intact and check.entries == 0
        assert EvidenceLedger(tmp_path).entries() == []


class TestLedgerTamperDetection:
    def test_edited_line_detected(self, tmp_path):
        ledger = EvidenceLedger(tmp_path)
        ledger.append("t1", "root-a")
        ledger.append("t1", "root-b")
        lines = ledger.path.read_text().splitlines()
        edited = json.loads(lines[0])
        edited["root"] = "forged-root"
        lines[0] = json.dumps(edited, sort_keys=True)
        ledger.path.write_text("\n".join(lines) + "\n")
        check = verify_ledger(tmp_path)
        assert not check.intact and check.first_bad_line == 1

    def test_deleted_line_detected(self, tmp_path):
        ledger = EvidenceLedger(tmp_path)
        ledger.append("t1", "root-a")
        ledger.append("t2", "root-b")
        ledger.append("t1", "root-c")
        lines = ledger.path.read_text().splitlines()
        del lines[1]  # remove t2's entry: t1 root-c's prev no longer matches
        ledger.path.write_text("\n".join(lines) + "\n")
        check = verify_ledger(tmp_path)
        assert not check.intact and check.first_bad_line == 2

    def test_garbage_line_detected(self, tmp_path):
        ledger = EvidenceLedger(tmp_path)
        ledger.append("t1", "root-a")
        with open(ledger.path, "a") as fh:
            fh.write("not json at all\n")
        check = verify_ledger(tmp_path)
        assert not check.intact and check.first_bad_line == 2
        assert "unparseable" in check.detail


class TestRollbackAudit:
    def test_rolled_back_trace_detected(self, store):
        trace = _signed_trace(store)
        v1_payload = trace.to_json()
        root1 = trace.meta["integrity"]["final"]

        # a legitimate later save (content changes, re-signed)
        trace.steps[0].result = "updated"
        sign(trace)
        store.save(trace)
        assert audit_rollback(trace, store.directory) is None  # latest

        # rollback: file replaced with the older correctly-signed state
        from approximately.trace import Trace

        old = Trace.from_json(v1_payload)
        assert old.meta["integrity"]["final"] == root1
        assert audit_rollback(old, store.directory) == "rolled-back"

    def test_no_history_no_flag(self, store):
        trace = _signed_trace(store)
        assert audit_rollback(trace, store.directory) is None

    def test_single_entry_never_flags(self, tmp_path):
        from approximately.trace import Trace

        ledger = EvidenceLedger(tmp_path)
        ledger.append("t1", "root-a")
        trace = Trace(task="t")
        trace.meta["integrity"] = {"final": "root-a"}
        assert audit_rollback(trace, tmp_path) is None  # no newer entry

    def test_unsigned_trace_ignored(self, tmp_path):
        rec = Recorder("plain", save=False)
        rec.respond("ok")
        assert audit_rollback(rec.trace, tmp_path) is None

    def test_tampered_root_matches_nothing(self, store):
        trace = _signed_trace(store)
        trace.meta["integrity"]["final"] = "bogus"
        assert audit_rollback(trace, store.directory) is None


class TestStoreIntegration:
    def test_save_appends_when_enabled(self, store):
        trace = _signed_trace(store)
        ledger = EvidenceLedger(store.directory)
        assert ledger.latest_root(trace.id) == \
            trace.meta["integrity"]["final"]
        assert verify_ledger(store.directory).intact

    def test_save_skips_unsigned_or_disabled(self, tmp_path, monkeypatch):
        monkeypatch.delenv("APPROXIMATELY_LEDGER", raising=False)
        store = TraceStore(tmp_path / "s1")
        _signed_trace(store)
        assert not ledger_path(store.directory).exists()

        monkeypatch.setenv("APPROXIMATELY_LEDGER", "1")
        store2 = TraceStore(tmp_path / "s2")
        rec = Recorder("no sig", store=store2, save=False)
        rec.respond("ok")  # never signed
        store2.save(rec.trace)
        assert not ledger_path(store2.directory).exists()

    def test_ledger_failure_never_fails_save(self, store, monkeypatch):
        trace = _signed_trace(store)
        trace.steps[0].result = "v2"
        sign(trace)
        # make the ledger path unwritable: replace file with a directory
        (store.directory / "ledger.jsonl").unlink()
        (store.directory / "ledger.jsonl").mkdir()
        store.save(trace)  # must not raise
