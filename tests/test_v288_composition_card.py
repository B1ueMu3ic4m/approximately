"""Night VII, round 8: the composition view reaches the postmortem.

``report.html`` renders a Context composition card — what fills the
run's window by step kind, worst contributor per kind — beside the
other analysis cards. Best-effort contract: nothing measurable, no
card.
"""

from approximately.attributor import attribute
from approximately.recorder import Recorder
from approximately.report import render_html


def _heavy_run():
    with Recorder("the heavy run", model="m/1", save=False) as rec:
        rec.plan("search, then book")
        rec.tool("search", {"q": 1}, result="x" * 8_000)
        rec.tool("verify", {"q": 2}, result="y" * 300)
        rec.respond("done", success=True)
    return rec.trace


def test_report_renders_the_composition_card():
    trace = _heavy_run()
    html = render_html(trace, attribute(trace))
    assert "Context composition" in html
    assert "tool_call" in html
    assert "91" in html or "90" in html  # tool_call dominates
    assert "total" in html


def test_respond_only_run_gets_no_card():
    with Recorder("talk only", model="m/1", save=False) as rec:
        rec.respond("just words", success=True)
    html = render_html(rec.trace, attribute(rec.trace))
    assert "Context composition" not in html


def test_poison_steps_never_break_the_card():
    with Recorder("weird", model="m/1", save=False) as rec:
        rec.tool("t", {"k": object()}, result="x" * 500)
        rec.respond("done", success=True)
    html = render_html(rec.trace, attribute(rec.trace))
    assert "Context composition" in html  # args stringify, not crash
