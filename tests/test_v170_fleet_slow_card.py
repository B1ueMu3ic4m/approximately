"""v170: the fleet dashboard shows the slow stores too.

Survey rows carried `fleet_anomalies` (v1.44) but the rendered
dashboard only showed failure rates — a store running
slow-but-successful looked perfectly healthy in the HTML. The store
card now grows a slowness section: outlier count plus the worst
step (tool, latency, family median, z).
"""

from approximately.fleet import render_fleet_html, survey
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
    slow = Recorder("the slow one", save=False)
    slow.tool("search", {"q": "heavy"}, result="hit")
    slow.respond("done", success=True)
    slow.trace.steps[0].latency_ms = 30000
    store.save(slow.trace)
    return store


def test_dashboard_shows_slow_outliers(tmp_path):
    _seed(tmp_path / "s")
    html = render_fleet_html(survey([tmp_path / "s"]))
    assert "slow outlier(s)" in html
    assert "Slowest step" in html
    assert "family median" in html
    assert "search" in html


def test_healthy_store_has_no_slowness_section(tmp_path):
    store = TraceStore(tmp_path / "calm")
    rec = Recorder("calm", save=False)
    rec.respond("done", success=True)
    store.save(rec.trace)
    html = render_fleet_html(survey([tmp_path / "calm"]))
    assert "slow outlier(s)" not in html
    assert "Slowest step" not in html
