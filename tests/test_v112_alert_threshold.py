"""v112: quiet-by-default alerting — `--alert-worse-than` gates the
watch webhook on signal, not schedule.

No threshold: every cycle posts (unchanged behavior). With a
threshold: a healthy fleet pages nobody — the POST fires only when a
store's trend is worsening or its failure rate is at/above the line.
Digest snapshots still land every cycle regardless; the threshold
gates the notification, never the recording.
"""

from approximately.fleet import StoreSummary, _should_alert, watch_fleet
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store(tmp_path, failure=False, name="s"):
    store = TraceStore(str(tmp_path / name))
    rec = Recorder("alert fixture", save=False)
    rec.tool("deploy", {"env": "prod"},
             result=None if failure else "ok")
    rec.respond("done", success=not failure)
    store.save(rec.trace)
    return store


def _summary(tmp_path, failure):
    from approximately.fleet import survey

    return survey([_store(tmp_path, failure=failure).directory])


def test_should_alert_no_threshold_always_true(tmp_path):
    assert _should_alert(_summary(tmp_path, failure=False), None) is True


def test_should_alert_threshold_blocks_healthy(tmp_path):
    assert _should_alert(_summary(tmp_path, failure=False), 0.5) is False


def test_should_alert_threshold_fires_on_rate(tmp_path):
    summaries = _summary(tmp_path, failure=True)  # 100% failure rate
    assert _should_alert(summaries, 0.5) is True


def test_should_alert_fires_on_worsening_even_below_rate(tmp_path):
    s = StoreSummary(name="x", path="/x", traces=10, failed=1,
                     failure_rate=0.1, trend_verdict="worsening",
                     trend_slope=0.2)  # worsening is a property
    assert _should_alert([s], 0.5) is True


def test_watch_threshold_gates_poster(tmp_path):
    calls = []

    def fake_poster(summaries, url):
        calls.append(url)
        return "200"

    digest_dir = tmp_path / "d"
    digest_dir.mkdir()
    store = _store(tmp_path, failure=False)  # healthy fleet
    written = watch_fleet([store.directory], digest_dir, interval=0,
                          iterations=3,
                          webhook_url="https://hooks.example/x",
                          notify=fake_poster, alert_worse_than=0.5)
    assert written == 3          # snapshots still recorded every cycle
    assert calls == []           # but nobody got paged
