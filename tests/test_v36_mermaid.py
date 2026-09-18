"""v0.36: mermaid sequence-diagram export.

Traces render as sequenceDiagrams that paste into GitHub markdown;
attributed failures become notes over the failing step; mermaid-
breaking characters in trace text are neutralized.
"""

from __future__ import annotations

from approximately.cli import cmd_report
from approximately.detectors import Detection
from approximately.mermaid import render_mermaid
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _trace():
    rec = Recorder("deploy the service; carefully", save=False)
    rec.plan("start: check config")
    rec.tool("assistant", {}, result="running deploy.sh --env prod")
    rec.respond("deployment complete")
    return rec.trace


class TestRender:
    def test_basic_structure(self):
        text = render_mermaid(_trace())
        assert text.startswith("sequenceDiagram\n")
        assert "participant U as User" in text
        assert "participant A as Agent" in text

    def test_steps_appear_in_order(self):
        text = render_mermaid(_trace())
        i_note = text.index("start - check config")
        i_tool = text.index("deploy.sh")
        i_final = text.index("deployment complete")
        assert i_note < i_tool < i_final

    def test_semicolons_and_colons_neutralized(self):
        text = render_mermaid(_trace())
        assert ";" not in text.split("sequenceDiagram\n")[1]

    def test_detection_becomes_warning_note(self):
        det = Detection("FM-3.2", 1,
                        ["mutating call was never verified"], 0.7)
        text = render_mermaid(_trace(), [det])
        assert "⚠ FM-3.2" in text
        assert text.index("⚠ FM-3.2") > text.index("deploy.sh")

    def test_long_text_excerpted(self):
        rec = Recorder("task", save=False)
        rec.plan("x" * 500)
        text = render_mermaid(rec.trace)
        assert len(text) < 700


class TestCli:
    def test_report_mermaid_flag_writes_file(self, tmp_path, capsys):
        store = TraceStore(str(tmp_path))
        trace = _trace()
        store.save(trace)
        args = type("A", (), {"store": str(tmp_path),
                              "trace": trace.id, "all": False,
                              "output": str(tmp_path / "r.html"),
                              "mermaid": str(tmp_path / "r.mmd"),
                              "judge": False})()
        assert cmd_report(args) == 0
        mmd = tmp_path / "r.mmd"
        assert mmd.exists()
        assert mmd.read_text(encoding="utf-8").startswith(
            "sequenceDiagram")
