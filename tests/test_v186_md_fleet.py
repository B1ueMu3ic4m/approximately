"""v186: markdown postmortems name fleet outliers too.

The HTML postmortem grew a Fleet-outliers card (v1.55); the markdown
issue-ready version gets the same section — an issue filed from the
markdown should carry the slowness evidence without opening the HTML.
"""

from approximately.attributor import attribute
from approximately.markdown_report import render_markdown
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed(directory):
    store = TraceStore(directory)
    jitter = (1800, 2000, 2100, 1900)
    for i in range(4):
        rec = Recorder(f"boring {i}", save=False)
        rec.tool("search", {"q": str(i)}, result="hit")
        rec.respond("done", success=True)
        rec.trace.steps[0].latency_ms = jitter[i]
        store.save(rec.trace)
    return store


def test_markdown_names_fleet_outliers(tmp_path):
    store = _seed(tmp_path / "s")
    slow = Recorder("the slow one", save=False)
    slow.tool("search", {"q": "heavy"}, result="hit")
    slow.respond("done", success=True)
    slow.trace.steps[0].latency_ms = 30000
    store.save(slow.trace)
    md = render_markdown(slow.trace, attribute(slow.trace), store)
    assert "### Fleet outliers" in md
    assert "family median" in md
    assert "`#0` search 30000ms" in md


def test_calm_trace_has_no_fleet_section(tmp_path):
    store = _seed(tmp_path / "s")
    calm = Recorder("calm run", save=False)
    calm.tool("search", {"q": "fine"}, result="hit")
    calm.respond("done", success=True)
    calm.trace.steps[0].latency_ms = 1950
    store.save(calm.trace)
    md = render_markdown(calm.trace, attribute(calm.trace), store)
    assert "### Fleet outliers" not in md


def test_no_store_no_fleet_section(tmp_path):
    rec = Recorder("orphan", save=False)
    rec.respond("done", success=True)
    md = render_markdown(rec.trace, attribute(rec.trace), None)
    assert "### Fleet outliers" not in md
