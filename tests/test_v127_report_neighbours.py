"""v127: the postmortem shows its nearest neighbours — "which runs
look like this one" right on the report, from the same store,
hidden when the store is empty or the trace is alone.
"""

from approximately.attributor import attribute
from approximately.markdown_report import render_markdown
from approximately.recorder import Recorder
from approximately.report import render_html
from approximately.store import TraceStore


def _store(tmp_path, with_neighbours=True):
    store = TraceStore(str(tmp_path / "s"))
    bad = Recorder("book the flight", save=False)
    bad.trace.id = "nb-bad"
    bad.tool("search", {"route": "SFO-NRT"}, result="$880")
    bad.tool("book", {"seat": "12A"}, result=None, error="timeout")
    bad.respond("gave up", success=False)
    store.save(bad.trace)
    if with_neighbours:
        twin = Recorder("book the flight", save=False)
        twin.trace.id = "nb-twin"
        twin.tool("search", {"route": "SFO-NRT"}, result="$880")
        twin.tool("book", {"seat": "13A"}, result=None, error="timeout")
        twin.respond("gave up", success=False)
        store.save(twin.trace)
    return store


def test_html_shows_neighbours(tmp_path):
    store = _store(tmp_path)
    trace = store.load("nb-bad")
    report = attribute(trace)
    html = render_html(trace, report, store=store)
    assert "Nearest neighbours" in html
    assert "nb-twin" in html
    assert "0." in html  # a similarity score


def test_markdown_shows_neighbours(tmp_path):
    store = _store(tmp_path)
    trace = store.load("nb-bad")
    report = attribute(trace)
    md = render_markdown(trace, report, store=store)
    assert "### Nearest neighbours" in md
    assert "nb-twin" in md


def test_alone_in_store_hides_section(tmp_path):
    store = _store(tmp_path, with_neighbours=False)
    trace = store.load("nb-bad")
    report = attribute(trace)
    html = render_html(trace, report, store=store)
    assert "Nearest neighbours" not in html
    md = render_markdown(trace, report, store=store)
    assert "### Nearest neighbours" not in md
