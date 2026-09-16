"""v0.26: replay HTML A/B page — structure, escaping, CLI wiring."""

from __future__ import annotations

from approximately.recorder import Recorder
from approximately.replayer import ReplayDiff, StepDiff, render_replay_html


def _diff(verdict="consistent", match_rate=0.9):
    steps = [
        StepDiff(index=1, kind="tool_call", tool="search",
                 recorded="found 3 flights", replayed="found 3 flights",
                 error=None, similarity=1.0, match=True),
        StepDiff(index=2, kind="tool_call", tool="book_flight",
                 recorded="BOOKED #B-2231", replayed="BOOKED #B-9999",
                 error=None, similarity=0.6, match=False),
    ]
    return ReplayDiff(trace_id="t-1", steps=steps, match_rate=match_rate,
                      verdict=verdict)


class TestRendering:
    def test_structure(self):
        html = render_replay_html(_diff())
        assert html.startswith("<!doctype html>")
        assert "Replay A/B" in html and "consistent" in html
        assert "90%" in html and "book_flight" in html

    def test_diverged_row_highlighted(self):
        html = render_replay_html(_diff(verdict="diverged"))
        assert 'class="diverged"' in html
        assert 'class="badge bad"' in html

    def test_ab_third_column(self):
        a = _diff(verdict="diverged")
        b = _diff(verdict="reproduced")
        html = render_replay_html(a, b)
        assert "patched executor" in html
        assert "BOOKED #B-9999" in html

    def test_hostile_content_escaped(self):
        a = _diff(verdict="diverged")
        a.trace_id = '"><script>x</script>'
        a.steps[1].recorded = "<script>alert(1)</script>"
        html = render_replay_html(a)
        assert "<script>" not in html


class TestCli:
    def test_replay_writes_html(self, tmp_path, capsys, monkeypatch):

        from approximately.cli import main
        from approximately.store import TraceStore

        store = TraceStore(tmp_path / "s")
        rec = Recorder("replay html", store=store, save=False)
        rec.tool("t", {}, result="ok")
        rec.respond("done")
        store.save(rec.trace)

        exec_mod = tmp_path / "fake_exec.py"
        exec_mod.write_text("def step(step):\n    return 'ok'\n")
        monkeypatch.syspath_prepend(str(tmp_path))
        out = tmp_path / "replay.html"
        rc = main(["--store", str(tmp_path / "s"), "replay", "latest",
                   "--executor", "fake_exec:step", "--html", str(out)])
        assert rc == 0
        assert "Replay A/B" in out.read_text()
