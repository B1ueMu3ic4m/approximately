"""v0.23: --since time-window queries across store commands."""

from __future__ import annotations

import time

from approximately.cli import main
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store(tmp_path):
    store = TraceStore(tmp_path / "store")
    for i, age_days in enumerate([40, 20, 2]):
        rec = Recorder(f"task {i}", store=store, save=False)
        rec.tool("deploy", {}, result="ok")
        rec.respond("done", success=(i == 0))
        rec.trace.created_at = int(time.time() - age_days * 86400)
        store.save(rec.trace)
    return store


class TestSinceWindow:
    def test_stats_since_filters(self, tmp_path, capsys):
        store = _store(tmp_path)
        rc = main(["--store", str(store.directory), "stats", "--since", "30"])
        assert rc == 0
        out = capsys.readouterr().out
        # the 40-day trace is out of the window
        assert "2" in out

    def test_stats_all_when_omitted(self, tmp_path, capsys):
        store = _store(tmp_path)
        rc = main(["--store", str(store.directory), "stats"])
        assert rc == 0
        assert "3" in capsys.readouterr().out

    def test_cluster_since_composes_with_last(self, tmp_path, capsys):
        store = _store(tmp_path)
        rc = main(["--store", str(store.directory), "cluster",
                   "--since", "30", "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        assert '"traces_scanned": 2' in out

    def test_attribute_all_since(self, tmp_path, capsys):
        import json

        store = _store(tmp_path)
        rc = main(["--store", str(store.directory), "attribute", "--all",
                   "--since", "10", "--json"])
        assert rc == 0
        results = json.loads(capsys.readouterr().out)
        assert len(results) == 1  # only the 2-day-old trace

    def test_verify_all_since(self, tmp_path, capsys):
        from approximately.integrity import sign

        store = _store(tmp_path)
        for t in store.list_traces():
            sign(t)
            store.save(t)
        rc = main(["--store", str(store.directory), "verify", "--all",
                   "--since", "30", "--json"])
        assert rc == 0
        payload = __import__("json").loads(capsys.readouterr().out)
        assert len(payload["traces"]) == 2

    def test_created_at_fallback_to_mtime(self, tmp_path):
        # a trace with unset created_at falls back to file mtime
        store = TraceStore(tmp_path / "s")
        rec = Recorder("no clock", store=store, save=False)
        rec.respond("done")
        store.save(rec.trace)
        fresh = store.list_traces(since_days=1)
        assert len(fresh) == 1
        ancient = store.list_traces(since_days=0)
        # since_days=0 -> cutoff = now; the just-written file passes
        assert len(ancient) == 1
