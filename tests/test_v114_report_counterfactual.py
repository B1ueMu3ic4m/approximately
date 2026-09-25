"""v114: the postmortem grows a counterfactual root-cause card.

Leave-one-out attribution answers "which step's removal eliminates
the mode" — the strongest causal language in the toolkit — but it
lived only in the CLI/MCP surfaces. Now the HTML and Markdown
reports carry it automatically, affordance-gated: traces longer than
200 steps skip the card (the render must stay linear; the standalone
`counterfactual` surface remains for those).
"""

from approximately.attributor import attribute
from approximately.markdown_report import render_markdown
from approximately.recorder import Recorder
from approximately.report import render_html
from approximately.store import TraceStore


def _store(tmp_path, steps=6):
    store = TraceStore(str(tmp_path / "s"))
    rec = Recorder("book the cheapest flight", save=False)
    rec.trace.id = "cf-1"
    rec.plan("search flights")
    rec.tool("search", {"route": "SFO-NRT"}, result="$880 found")
    rec.tool("search", {"route": "SFO-NRT"}, result="$880 found")
    rec.tool("book", {"seat": "12A"}, result=None, error="timeout")
    rec.tool("retry", {}, result=None, error="timeout")
    for i in range(max(0, steps - 5)):
        rec.tool("probe", {"i": i}, result="ok")
    rec.respond("gave up", success=False)
    store.save(rec.trace)
    return store


def test_html_card_present(tmp_path):
    store = _store(tmp_path)
    trace = store.load("cf-1")
    report = attribute(trace)
    html = render_html(trace, report)
    assert "Root cause (counterfactual)" in html or \
        "Distributed causes" in html


def test_markdown_section_present(tmp_path):
    store = _store(tmp_path)
    trace = store.load("cf-1")
    report = attribute(trace)
    md = render_markdown(trace, report)
    assert "### Root cause (counterfactual)" in md or \
        "distributed:" in md


def test_long_traces_skip_the_card(tmp_path):
    store = _store(tmp_path, steps=260)
    trace = store.load("cf-1")
    assert len(trace.steps) > 200
    report = attribute(trace)
    html = render_html(trace, report)
    assert "Root cause (counterfactual)" not in html
    md = render_markdown(trace, report)
    assert "### Root cause (counterfactual)" not in md


def test_clean_run_has_no_card(tmp_path):
    store = TraceStore(str(tmp_path / "ok"))
    rec = Recorder("fine", save=False)
    rec.trace.id = "ok-1"
    rec.tool("search", {"q": 1}, result="hit")
    rec.respond("done", success=True)
    store.save(rec.trace)
    trace = store.load("ok-1")
    report = attribute(trace)
    html = render_html(trace, report)
    assert "Root cause (counterfactual)" not in html
