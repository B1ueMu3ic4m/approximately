"""v0.19: verify --all — batch integrity audit over a whole store."""

from __future__ import annotations

import json

import pytest

from approximately.cli import main
from approximately.integrity import sign
from approximately.ledger import EvidenceLedger
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store(tmp_path, builders, sign_traces=True):
    store = TraceStore(tmp_path / "store")
    for name, build in builders.items():
        rec = Recorder(name, store=store, save=False)
        rec.tool("t", {}, result="ok")
        rec.respond("done")
        if sign_traces:
            sign(rec.trace)
        build(rec)  # runs after signing: may tamper the signed state
        store.save(rec.trace)
    return store


def _clean(rec):
    pass


class TestVerifyAll:
    def test_all_intact(self, tmp_path, capsys):
        store = _store(tmp_path, {"a": _clean, "b": _clean})
        rc = main(["--store", str(store.directory), "verify", "--all"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "2 intact" in out and "0 failed" in out

    def test_unsigned_counted_not_fatal(self, tmp_path, capsys):
        store = _store(tmp_path,
                       {"signed": lambda rec: sign(rec.trace),
                        "plain": _clean},
                       sign_traces=False)
        rc = main(["--store", str(store.directory), "verify", "--all"])
        assert rc == 0  # unsigned is a state, not a failure
        assert "1 unsigned" in capsys.readouterr().out

    def test_tampered_fails_batch(self, tmp_path, capsys):
        def forge(rec):
            rec.trace.steps[0].result = "edited after signing"

        store = _store(tmp_path, {"good": _clean, "bad": forge})
        rc = main(["--store", str(store.directory), "verify", "--all"])
        assert rc == 1
        out = capsys.readouterr().out
        assert "<-- TAMPERED" in out and "1 failed" in out

    def test_rolled_back_fails_batch(self, tmp_path, monkeypatch,
                                     capsys):
        monkeypatch.setenv("APPROXIMATELY_LEDGER", "1")
        store = TraceStore(tmp_path / "s")
        rec = Recorder("rb", store=store, save=False)
        rec.tool("t", {}, result="v1")
        rec.respond("done")
        sign(rec.trace)
        v1 = rec.trace.to_json()
        store.save(rec.trace)
        rec.trace.steps[0].result = "v2"
        sign(rec.trace)
        store.save(rec.trace)
        # roll the file back to the older signed snapshot
        from approximately.trace import Trace

        old = Trace.from_json(v1)
        store.save(old)

        rc = main(["--store", str(store.directory), "verify", "--all"])
        assert rc == 1
        assert "rolled-back" in capsys.readouterr().out

    def test_broken_ledger_reported(self, tmp_path, capsys):
        store = _store(tmp_path, {"a": _clean})
        EvidenceLedger(store.directory).append("x", "root-x")
        (store.directory / "ledger.jsonl").write_text("garbage\n")
        rc = main(["--store", str(store.directory), "verify", "--all"])
        out = capsys.readouterr().out
        # traces are unsigned -> clean, but the broken ledger surfaces
        assert "LEDGER BROKEN" in out
        assert rc == 1

    def test_empty_store_clean(self, tmp_path, capsys):
        TraceStore(tmp_path / "empty")
        rc = main(["--store", str(tmp_path / "empty"), "verify", "--all"])
        assert rc == 0
        assert "0 intact" in capsys.readouterr().out


class TestVerifyAllJson:
    def test_json_output(self, tmp_path, capsys):
        store = _store(tmp_path, {"a": _clean, "b": _clean})
        rc = main(["--store", str(store.directory), "verify", "--all",
                   "--json"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["summary"]["intact"] == 2
        assert payload["ledger_broken"] is False
        assert len(payload["traces"]) == 2
        assert all(t["verdict"] == "intact" for t in payload["traces"])

    def test_json_exit_code_on_problem(self, tmp_path, capsys):
        def forge(rec):
            rec.trace.steps[0].result = "edited after signing"

        store = _store(tmp_path, {"a": _clean, "bad": forge})
        rc = main(["--store", str(store.directory), "verify", "--all",
                   "--json"])
        assert rc == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["summary"]["problem"] == 1
        assert any(t["verdict"] == "TAMPERED" for t in payload["traces"])


class TestLatestResolution:
    def test_load_trace_latest(self, tmp_path, capsys):
        import time

        from approximately.cli import main
        from approximately.store import TraceStore

        store = TraceStore(tmp_path / "s")
        for i, name in enumerate(["older", "newer"]):
            rec = Recorder(name, store=store, save=False)
            rec.tool("t", {}, result=name)
            rec.respond("done")
            sign(rec.trace)
            rec.trace.created_at = int(time.time()) - (10 - i) * 60
            store.save(rec.trace)

        rc = main(["--store", str(tmp_path / "s"), "attribute", "latest"])
        assert rc == 0
        out = capsys.readouterr().out
        # both traces share the task names; the verdict comes from the
        # newest one - success=True means 'newer' was loaded
        assert "No failure detected" in out

    def test_latest_on_empty_store(self, tmp_path, capsys):
        from approximately.cli import main
        from approximately.store import TraceStore

        TraceStore(tmp_path / "empty")
        with pytest.raises(SystemExit, match="is empty"):
            main(["--store", str(tmp_path / "empty"), "attribute",
                  "latest"])
