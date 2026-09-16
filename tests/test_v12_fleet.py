"""v0.12: fleet dashboard — multi-store survey, aggregation, HTML page."""

from __future__ import annotations

from approximately.fleet import render_fleet_html, survey
from approximately.ledger import EvidenceLedger
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _populate(path, runs, ledger_roots=()):
    """runs: list of (success, tools) tuples."""
    store = TraceStore(path)
    for i, (success, tools) in enumerate(runs):
        rec = Recorder(f"task {i}", store=store, save=False)
        for tool in tools:
            rec.tool(tool, {}, result="ok")
        rec.respond("done", success=success)
        store.save(rec.trace)
    for trace_id, root in ledger_roots:
        EvidenceLedger(path).append(trace_id, root)
    return store


def _failing(path, n):
    runs = [(False, ["deploy"])] * n
    return _populate(path, runs)


class TestSurvey:
    def test_counts_and_rates(self, tmp_path):
        _populate(tmp_path / "healthy", [(True, ["a"]), (True, ["b"])])
        _populate(tmp_path / "sick", [(True, ["a"]), (False, ["deploy"]),
                                      (False, ["deploy"])])
        summaries = survey([tmp_path / "healthy", tmp_path / "sick"])
        by_name = {s.name: s for s in summaries}
        assert by_name["healthy"].failure_rate == 0.0
        assert by_name["sick"].traces == 3
        assert abs(by_name["sick"].failure_rate - 2 / 3) < 1e-9

    def test_top_modes_via_rules(self, tmp_path):
        store = TraceStore(tmp_path / "loopy")
        for _ in range(2):
            rec = Recorder("scroll the page", store=store, save=False)
            for _ in range(6):
                rec.tool("scroll", {"n": 1}, result="same")
            rec.respond("gave up", success=False)
            store.save(rec.trace)
        summaries = survey([tmp_path / "loopy"])
        modes = summaries[0].top_modes
        assert modes and modes[0][0].startswith("FM-")

    def test_empty_store(self, tmp_path):
        TraceStore(tmp_path / "empty")
        summaries = survey([tmp_path / "empty"])
        s = summaries[0]
        assert s.traces == 0 and s.failure_rate == 0.0
        assert s.top_modes == []

    def test_ledger_state_reported(self, tmp_path):
        store = _populate(tmp_path / "led", [(True, ["a"])])
        trace = store.list_traces()[0]
        EvidenceLedger(tmp_path / "led").append(
            trace.id, trace.meta.get("integrity", {}).get("final", "x"))
        summaries = survey([tmp_path / "led", tmp_path / "n led"])
        assert summaries[0].ledger_intact is True
        assert summaries[1].ledger_intact is None  # no ledger file

    def test_broken_ledger_flagged(self, tmp_path):
        store = _populate(tmp_path / "led", [(True, ["a"])])
        ledger_path = tmp_path / "led" / "ledger.jsonl"
        ledger_path.write_text("garbage line\n")
        summaries = survey([tmp_path / "led"])
        assert summaries[0].ledger_intact is False
        assert store  # keeps fixture used


class TestFleetHtml:
    def test_structure_and_kpis(self, tmp_path):
        _populate(tmp_path / "a", [(True, ["x"]), (False, ["deploy"])])
        summaries = survey([tmp_path / "a"])
        html = render_fleet_html(summaries)
        assert html.startswith("<!doctype html>")
        assert "Fleet dashboard" in html
        assert "50.0%" in html  # fleet failure rate KPI
        assert "2</div>" in html or ">2<" in html  # traces KPI

    def test_store_names_and_paths_escaped(self, tmp_path):
        nasty = tmp_path / '"><script>alert(1)'
        nasty.mkdir()
        TraceStore(nasty)
        html = render_fleet_html(survey([nasty]))
        assert "<script>" not in html
        assert "&gt;" in html or "&quot;" in html

    def test_empty_fleet(self):
        html = render_fleet_html([])
        assert "No stores surveyed" in html

    def test_broken_ledger_badge(self, tmp_path):
        _populate(tmp_path / "led", [(True, ["a"])])
        (tmp_path / "led" / "ledger.jsonl").write_text("junk\n")
        html = render_fleet_html(survey([tmp_path / "led"]))
        assert "LEDGER BROKEN" in html


class TestCli:
    def test_fleet_command(self, tmp_path, capsys):
        from approximately.cli import main

        _populate(tmp_path / "s1", [(True, ["x"]), (False, ["deploy"])])
        out = tmp_path / "fleet.html"
        rc = main(["--store", str(tmp_path / "unused"),
                   "fleet", str(tmp_path / "s1"),
                   "--fleet-html", str(out)])
        assert rc == 0
        text = capsys.readouterr().out
        assert "s1: 2 traces, failure rate 50%" in text
        assert "Fleet dashboard" in out.read_text()
