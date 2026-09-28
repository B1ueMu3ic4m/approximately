"""v165: postmortems name fleet outliers.

The per-trace latency card only knows what this one run considered
normal. When a store is given, the postmortem gains a "Fleet
outliers" card: steps that are extreme against every stored run of
the same tool — a trace can look normal alone and still be the
slowest search the store has ever seen. Best-effort, like every
card: no store, no card.
"""

from approximately.recorder import Recorder
from approximately.report import render_html
from approximately.store import TraceStore


def _seed_store(directory):
    store = TraceStore(directory)
    jitter = (1800, 2000, 2100, 1900)
    for i in range(4):
        rec = Recorder(f"boring {i}", save=False)
        rec.tool("search", {"q": str(i)}, result="hit")
        rec.respond("done", success=True)
        rec.trace.steps[0].latency_ms = jitter[i]
        store.save(rec.trace)
    return store


def test_fleet_card_flags_the_outlier_step(tmp_path):
    store = _seed_store(tmp_path / "s")
    slow = Recorder("the slow one", save=False)
    slow.tool("search", {"q": "heavy"}, result="hit")
    slow.respond("done", success=True)
    slow.trace.steps[0].latency_ms = 30000
    store.save(slow.trace)
    from approximately.attributor import attribute

    html = render_html(slow.trace, attribute(slow.trace), store)
    assert "Fleet outliers" in html
    assert "family median" in html
    assert "search" in html


def test_no_store_no_card(tmp_path):
    rec = Recorder("orphan", save=False)
    rec.respond("done", success=True)
    from approximately.attributor import attribute

    html = render_html(rec.trace, attribute(rec.trace), None)
    assert "Fleet outliers" not in html


def test_quiet_trace_has_no_fleet_card(tmp_path):
    store = _seed_store(tmp_path / "s")
    calm = Recorder("calm run", save=False)
    calm.tool("search", {"q": "fine"}, result="hit")
    calm.respond("done", success=True)
    calm.trace.steps[0].latency_ms = 1950
    store.save(calm.trace)
    from approximately.attributor import attribute

    html = render_html(calm.trace, attribute(calm.trace), store)
    assert "Fleet outliers" not in html
