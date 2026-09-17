"""v0.34: fleet watch loop — JSONL digest snapshots with rotation."""

from __future__ import annotations

import json

from approximately.cli import cmd_fleet
from approximately.fleet import (
    StoreSummary,
    append_digest,
    digest_snapshot,
    rotate_digests,
    watch_fleet,
)


def _summary(name: str, rate: float, verdict: str = "stable"):
    return StoreSummary(name=name, path=f"/tmp/{name}", traces=10,
                        failed=int(rate * 10), failure_rate=rate,
                        trend_verdict=verdict)


class TestSnapshot:
    def test_snapshot_shape(self):
        snap = digest_snapshot([_summary("a", 0.4, "worsening")])
        assert snap["worsening"] == ["a"]
        store = snap["stores"][0]
        assert store["name"] == "a"
        assert store["failure_rate"] == 0.4
        assert "ts" in snap

    def test_append_digest_daily_file(self, tmp_path):
        path = append_digest(tmp_path, {"ts": 1.0, "stores": []})
        assert path.name.startswith("digest-")
        assert path.parent == tmp_path
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert json.loads(lines[0])["ts"] == 1.0

    def test_appends_accumulate(self, tmp_path):
        for ts in (1.0, 2.0):
            append_digest(tmp_path, {"ts": ts, "stores": []})
        lines = (tmp_path / append_digest(
            tmp_path, {"ts": 3.0, "stores": []}).name
        ).read_text().strip().splitlines()
        assert len(lines) == 3


class TestRotation:
    def test_old_files_removed(self, tmp_path):
        import os
        import time as time_mod

        old = tmp_path / "digest-20200101.jsonl"
        old.write_text("{}\n", encoding="utf-8")
        past = time_mod.time() - 90 * 86400
        os.utime(old, (past, past))
        keep = tmp_path / "digest-20990101.jsonl"
        keep.write_text("{}\n", encoding="utf-8")
        removed = rotate_digests(tmp_path, keep_days=30)
        assert removed == [old]
        assert not old.exists() and keep.exists()


class TestWatchLoop:
    def test_bounded_iterations_with_injectable_sleep(self, tmp_path):
        sleeps = []
        written = watch_fleet([], tmp_path, interval=60.0,
                              iterations=3, sleep=sleeps.append)
        assert written == 3
        assert sleeps == [60.0, 60.0, 60.0]
        files = list(tmp_path.glob("digest-*.jsonl"))
        assert len(files) == 1
        assert len(files[0].read_text().strip().splitlines()) == 3

    def test_snapshots_carry_store_rows(self, tmp_path):
        empty = tmp_path / "store-empty"
        empty.mkdir()
        watch_fleet([empty], tmp_path / "digests", interval=0.0,
                    iterations=1, sleep=lambda s: None)
        digest_dir = tmp_path / "digests"
        lines = next(digest_dir.glob("digest-*.jsonl")).read_text()
        snap = json.loads(lines.strip())
        assert len(snap["stores"]) == 1
        assert snap["stores"][0]["traces"] == 0


class TestCli:
    def test_cli_watch_flag_runs_bounded(self, tmp_path):
        store = tmp_path / "s"
        store.mkdir()
        args = type("A", (), {"stores": [str(store)],
                              "watch": 0.01, "iterations": 2,
                              "digest_dir": str(tmp_path / "d"),
                              "keep_days": 30, "json": False,
                              "fleet_html": None, "webhook": None,
                              "fail_on_worsening": False})()
        assert cmd_fleet(args) == 0
        assert len(list((tmp_path / "d").glob("digest-*.jsonl"))) == 1
