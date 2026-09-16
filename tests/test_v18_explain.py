"""v0.18: fusion explain — auditable arithmetic for every verdict."""

from __future__ import annotations

from approximately.attributor import attribute, explain_fusion
from approximately.recorder import Recorder


def _repeat_trace():
    rec = Recorder("explain task", save=False)
    for _ in range(5):
        rec.tool("scroll", {"n": 1}, result="same content")
    rec.respond("gave up", success=False)
    return rec.trace


class TestExplainFusion:
    def test_lines_cover_every_detection(self):
        report = attribute(_repeat_trace())
        text = explain_fusion(report.detections)
        for det in report.detections:
            assert det.mode_id in text
            assert det.source in text

    def test_verdict_line_is_ranked(self):
        report = attribute(_repeat_trace())
        text = explain_fusion(report.detections)
        verdict = [line for line in text.splitlines()
                   if line.startswith("  =>")]
        assert verdict, "verdict line missing"
        modes = verdict[0].split("verdict: ")[1].split(" > ")
        top = report.detections[0].mode_id
        assert modes[0] == top

    def test_prior_and_llr_sum_to_score(self):
        import math
        import re

        report = attribute(_repeat_trace())
        text = explain_fusion(report.detections)
        for line in text.splitlines():
            m = re.search(
                r"log-odds ([+-][\d.]+)\) \+ LLR ([+-][\d.]+)\s*= "
                r"([+-][\d.]+)", line)
            if m:
                prior, llr, total = (float(g) for g in m.groups())
                assert math.isclose(prior + llr, total, abs_tol=0.02)  # 2dp display

    def test_empty_detections(self):
        assert explain_fusion([]) == "no detections to explain"

    def test_cli_flag(self, tmp_path, capsys):
        from approximately.cli import main
        from approximately.store import TraceStore

        store = TraceStore(tmp_path / "s")
        store.save(_repeat_trace())
        tid = store.list_traces()[0].id
        rc = main(["--store", str(tmp_path / "s"), "attribute", tid,
                   "--explain"])
        assert rc == 0
        assert "fusion ranking" in capsys.readouterr().out
