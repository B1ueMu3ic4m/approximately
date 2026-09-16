"""v0.13: fleet trend alerts — worsening verdicts wired to CI exit codes."""

from __future__ import annotations

import time

from approximately.cli import main
from approximately.fleet import survey
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _populate(path, runs, ages_days):
    store = TraceStore(path)
    for (success, tools), age in zip(runs, ages_days):
        rec = Recorder(f"task {age}", store=store, save=False)
        for tool in tools:
            rec.tool(tool, {}, result="ok")
        rec.respond("done", success=success)
        rec.trace.created_at = int(time.time() - age * 86400)
        store.save(rec.trace)


class TestVerdicts:
    def test_worsening_store_detected(self, tmp_path):
        _populate(tmp_path / "bad",
                  [(True, ["a"]), (True, ["b"]), (False, ["deploy"]),
                   (False, ["deploy"]), (False, ["deploy"]),
                   (False, ["deploy"])],
                  ages_days=[30, 30, 20, 20, 10, 3])
        s = survey([tmp_path / "bad"])[0]
        assert s.worsening is True and s.trend_verdict == "worsening"

    def test_stable_store_not_flagged(self, tmp_path):
        _populate(tmp_path / "ok",
                  [(True, ["a"]), (False, ["deploy"]), (True, ["b"]),
                   (False, ["deploy"])],
                  ages_days=[30, 30, 10, 10])
        s = survey([tmp_path / "ok"])[0]
        assert s.worsening is False

    def test_verdict_badge_reaches_html(self, tmp_path):
        from approximately.fleet import render_fleet_html

        _populate(tmp_path / "bad",
                  [(True, ["a"]), (True, ["b"]), (False, ["deploy"]),
                   (False, ["deploy"]), (False, ["deploy"]),
                   (False, ["deploy"])],
                  ages_days=[30, 30, 20, 20, 10, 3])
        html = render_fleet_html(survey([tmp_path / "bad"]))
        assert "failure rate rising" in html


class TestCiGate:
    def test_fail_on_worsening_exit_code(self, tmp_path, capsys):
        _populate(tmp_path / "bad",
                  [(True, ["a"]), (True, ["b"]), (False, ["deploy"]),
                   (False, ["deploy"]), (False, ["deploy"]),
                   (False, ["deploy"])],
                  ages_days=[30, 30, 20, 20, 10, 3])
        rc = main(["fleet", str(tmp_path / "bad"), "--fail-on-worsening"])
        assert rc == 1
        assert "FAIL: worsening" in capsys.readouterr().out

    def test_pass_when_stable(self, tmp_path, capsys):
        _populate(tmp_path / "ok",
                  [(True, ["a"]), (False, ["deploy"]), (True, ["b"]),
                   (False, ["deploy"])],
                  ages_days=[30, 30, 10, 10])
        rc = main(["fleet", str(tmp_path / "ok"), "--fail-on-worsening"])
        assert rc == 0
        assert "FAIL" not in capsys.readouterr().out
