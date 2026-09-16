"""v0.12: MAD-based latency anomalies — statistics, thresholds, report."""

from __future__ import annotations

from approximately.anomaly import (
    detect_latency_anomalies,
    summarize_anomalies,
)
from approximately.recorder import Recorder


def _trace(latencies, tool="call_tool"):
    rec = Recorder("anomaly task", save=False)
    for ms in latencies:
        rec.tool(tool, {"n": 1}, result="ok")
        rec.trace.steps[-1].latency_ms = ms
    rec.respond("done")
    return rec.trace


NORMAL = [120, 135, 118, 142, 127, 131, 122, 139, 125, 130]


class TestDetection:
    def test_extreme_outlier_flagged(self):
        trace = _trace((*NORMAL, 20000))
        anomalies = detect_latency_anomalies(trace)
        assert len(anomalies) == 1
        assert anomalies[0].latency_ms == 20000
        assert anomalies[0].direction == "slow"
        assert anomalies[0].robust_z > 3.5

    def test_normal_trace_clean(self):
        assert detect_latency_anomalies(_trace(NORMAL)) == []

    def test_sorted_by_abs_z(self):
        trace = _trace((*NORMAL, 900, 40000))
        anomalies = detect_latency_anomalies(trace)
        assert [a.latency_ms for a in anomalies] == [40000, 900]

    def test_fast_outlier_flagged_too(self):
        trace = _trace((*NORMAL, 1))
        anomalies = detect_latency_anomalies(trace)
        assert len(anomalies) == 1 and anomalies[0].direction == "fast"

    def test_threshold_respected(self):
        trace = _trace((*NORMAL, 200))  # z ~ 7: flagged at 3.5, not at 10
        loose = detect_latency_anomalies(trace, threshold=10.0)
        tight = detect_latency_anomalies(trace, threshold=3.5)
        assert tight and not loose

    def test_min_samples_floor(self):
        trace = _trace([120, 130, 90000])
        assert detect_latency_anomalies(trace) == []  # too few samples
        assert detect_latency_anomalies(trace, min_samples=2)  # opt-in

    def test_mad_zero_is_degenerate_not_broken(self):
        trace = _trace([100] * 6 + [100, 5000])  # all identical...
        # ...so MAD=0: honest "no scale information", no anomalies
        assert detect_latency_anomalies(trace) == []

    def test_non_tool_and_zero_latency_ignored(self):
        rec = Recorder("mixed", save=False)
        for ms in (*NORMAL, 30000):
            rec.plan("thinking")
            rec.tool("t", {}, result="ok")
            rec.trace.steps[-1].latency_ms = ms
        rec.observe("zero-latency step")  # kind != tool_call
        rec.respond("done")
        anomalies = detect_latency_anomalies(rec.trace)
        assert all(a.step_index != rec.trace.steps[-1].index
                   for a in anomalies)
        assert anomalies and anomalies[0].latency_ms == 30000

    def test_summary(self):
        assert summarize_anomalies([]) == "no latency anomalies"
        text = summarize_anomalies(detect_latency_anomalies(
            _trace((*NORMAL, 20000))))
        assert "median" in text and "z=" in text and "20000ms" in text


class TestReportCard:
    def test_card_only_when_anomalies(self):
        from approximately.report import _latency_card

        assert _latency_card(_trace(NORMAL)) == ""
        assert "Latency anomalies" in _latency_card(_trace((*NORMAL, 20000)))

    def test_card_escapes_tool_names(self):
        from approximately.report import _latency_card

        rec = Recorder("esc", save=False)
        for ms in (*NORMAL, 20000):
            rec.tool('"><script>', {}, result="ok")
            rec.trace.steps[-1].latency_ms = ms
        rec.respond("done")
        assert "<script>" not in _latency_card(rec.trace)


class TestCli:
    def test_anomalies_command_exit_codes(self, tmp_path, capsys):
        from approximately.cli import main
        from approximately.store import TraceStore

        store = TraceStore(tmp_path / "store")
        rec = Recorder("cli case", store=store, save=False)
        for ms in (*NORMAL, 20000):
            rec.tool("t", {}, result="ok")
            rec.trace.steps[-1].latency_ms = ms
        rec.respond("done")
        store.save(rec.trace)
        tid = store.list_traces()[0].id

        rc = main(["--store", str(store.directory), "anomalies", tid])
        assert rc == 1  # anomalies found -> nonzero for CI use
        assert "20000ms" in capsys.readouterr().out
