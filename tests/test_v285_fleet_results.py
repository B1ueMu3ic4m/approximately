"""Night VII, round 4: result bloat goes fleet-wide.

The third meter mirrors the token family across every fleet surface:
StoreSummary count + worst finding, webhook payload, digest day-rows
and the result-bloat trend curve, the store card, and alerting via
`fleet --alert-results N` with the usual cooldown dedup.
"""

import json

from approximately.anomaly import detect_fleet_result_anomalies
from approximately.fleet import (
    StoreSummary,
    _alert_reasons,
    _should_alert,
    _store_card,
    survey,
    webhook_payload,
)
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _noisy(tmp_path, walls=1, clean=2):
    store = TraceStore(tmp_path / "s")
    for i in range(clean):
        with Recorder(f"calm {i}", model="m/1", store=store) as rec:
            rec.tool("t", {}, result="x" * 100)
            rec.respond("done", success=True)
    for i in range(walls):
        with Recorder(f"bloat {i}", model="m/1", store=store) as rec:
            for j in range(5):
                rec.tool("list", {"j": j}, result="x" * 100)
            rec.tool("dump", {}, result="y" * 20_000)
            rec.respond("done", success=True)
    return store


def test_summary_counts_and_names_the_worst(tmp_path):
    store = _noisy(tmp_path)
    s = survey([store.directory])[0]
    assert s.result_anomalies >= 1
    worst = s.worst_result_anomaly
    assert worst is not None
    assert worst["tool"] == "dump"
    assert worst["result_chars"] == 20_000


def test_payload_carries_the_field(tmp_path):
    store = _noisy(tmp_path)
    payload = webhook_payload(survey([store.directory]))
    assert payload["stores"][0]["result_anomalies"] >= 1


def test_fleet_meter_agrees_with_the_summary(tmp_path):
    store = _noisy(tmp_path)
    flags = detect_fleet_result_anomalies(store.list_traces())
    s = survey([store.directory])[0]
    assert s.result_anomalies == len(flags)


def test_card_renders_result_bloat(tmp_path):
    store = _noisy(tmp_path)
    html = _store_card(survey([store.directory])[0])
    assert "result bloat(s)" in html
    assert "Longest result" in html
    assert "20,000 chars" in html
    clean = StoreSummary(name="c", path="/c")
    assert "result bloat" not in _store_card(clean)


def test_should_alert_on_result_threshold():
    bloated = StoreSummary(name="a", path="/a", result_anomalies=3)
    calm = StoreSummary(name="b", path="/b")
    assert _should_alert([bloated], None, None, None, None, None,
                         1) is True
    assert _should_alert([bloated], None, None, None, None, None,
                         4) is False
    assert _should_alert([calm], None, None, None, None, None,
                         1) is False


def test_alert_reason_names_the_store():
    bloated = StoreSummary(name="prod", path="/p",
                           result_anomalies=2)
    reasons = _alert_reasons([bloated], None, None, None, None, None,
                             1)
    assert "prod:result-bloat" in reasons


def test_watch_renders_the_result_curve(tmp_path):
    from approximately.fleet import _trend_section, summarize_trend
    # synthesized _trend_row-shaped days (summarize_trend consumes
    # rows, not trend_days entries)
    days = [{"day": f"2026-10-0{d}", "snapshots": 1,
             "last": {"stores": [{"result_anomalies": n}]}}
            for d, n in zip(range(1, 4), [1, 3, 6], strict=True)]
    html = _trend_section(summarize_trend(days))
    assert "result bloat:" in html
    assert "result bloat" in html  # day-table column


def test_digest_rows_carry_the_count(tmp_path):
    store = _noisy(tmp_path)
    from approximately.fleet import digest_snapshot, survey
    line = json.dumps(digest_snapshot(survey([store.directory])))
    payload = json.loads(line)
    assert any(s.get("result_anomalies", 0) >= 1
               for s in payload["stores"])


def test_tool_scorecard_ranks_the_dumper(tmp_path):
    store = _noisy(tmp_path)
    from approximately.cluster import tool_scorecard
    rows = {r["tool"]: r for r in tool_scorecard(store.list_traces())}
    assert rows["dump"]["result_chars"] == 20_000
    assert rows["t"]["result_chars"] == 200  # one "t" call per run
