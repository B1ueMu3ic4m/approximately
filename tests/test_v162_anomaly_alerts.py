"""v162: slowness pages too — `--alert-anomalies N`.

The watch webhook already fires on worsening trends and failure-rate
thresholds; fleet latency outliers now count as signal as well. A
store carrying >= N fleet outliers trips the alert even when every
run "succeeded" — the slow kind of failure used to page nobody.
"""

from approximately.fleet import _should_alert, watch_fleet
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _slow_store(tmp_path, name="slow"):
    store = TraceStore(str(tmp_path / name))
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


def _healthy_store(tmp_path, name="calm"):
    store = TraceStore(str(tmp_path / name))
    rec = Recorder("calm", save=False)
    rec.respond("done", success=True)
    store.save(rec.trace)
    return store


def _summary(path):
    from approximately.fleet import survey

    return survey([path])


def test_anomaly_threshold_blocks_healthy(tmp_path):
    summaries = _summary(_healthy_store(tmp_path).directory)
    assert _should_alert(summaries, 0.5, alert_anomalies=1) is False


def test_anomaly_threshold_fires_on_outliers(tmp_path):
    summaries = _summary(_slow_store(tmp_path).directory)
    assert _should_alert(summaries, 0.5, alert_anomalies=1) is True


def test_no_threshold_still_always_fires(tmp_path):
    summaries = _summary(_healthy_store(tmp_path).directory)
    assert _should_alert(summaries, None, alert_anomalies=1) is True


def test_watch_posts_on_anomaly_spike(tmp_path):
    posted = []
    store = _slow_store(tmp_path / "s")
    digest = tmp_path / "d"
    watch_fleet([store.directory], digest, interval=0.0,
                iterations=1, webhook_url="http://hook",
                notify=lambda summaries, url: posted.append(url),
                alert_worse_than=0.99,
                alert_anomalies=1)
    assert posted == ["http://hook"]


def test_watch_stays_quiet_below_threshold(tmp_path):
    posted = []
    store = _healthy_store(tmp_path / "s")
    digest = tmp_path / "d"
    watch_fleet([store.directory], digest, interval=0.0,
                iterations=1, webhook_url="http://hook",
                notify=lambda summaries, url: posted.append(url),
                alert_worse_than=0.99,
                alert_anomalies=1)
    assert posted == []
