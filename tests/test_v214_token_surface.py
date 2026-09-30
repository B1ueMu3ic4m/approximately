"""v214: token anomalies reach the surfaces people actually read.

v2.3.0 gave the detectors a token meter; this round puts the
findings where the latency ones already live — the per-trace HTML
report and the fleet summary + store card — so a burn shows up in
the same glance as a slowdown.
"""

import json

from approximately import report
from approximately.fleet import survey
from approximately.store import TraceStore
from approximately.trace import Step, Trace


def _burn_trace(ident="loopy"):
    trace = Trace(task="loopy run", id=ident, created_at=1.0)
    for tokens in (110, 95, 105, 90, 100, 115, 85, 120, 108, 92):
        trace.add(Step(kind="tool_call", tool="search",
                       tokens=tokens, latency_ms=40))
    trace.add(Step(kind="tool_call", tool="search", tokens=9000,
                   latency_ms=40))
    trace.add(Step(kind="response", result="done"))
    return trace


def _calm_trace(ident="calm"):
    trace = Trace(task="calm run", id=ident, created_at=1.0)
    for i in range(11):
        trace.add(Step(kind="tool_call", tool="search",
                       tokens=95 + (i % 3), latency_ms=40))
    trace.add(Step(kind="response", result="done"))
    return trace


def test_report_shows_token_card(tmp_path):
    from approximately.attributor import attribute

    store = TraceStore(tmp_path / "s")
    store.save(_burn_trace())
    trace = store.load("loopy")
    html = report.render_html(trace, attribute(trace), store=store)
    assert "Token anomalies" in html
    assert "9000" in html
    assert "burn" in html
    assert "retry loop" in html


def test_report_calm_run_has_no_token_card(tmp_path):
    from approximately.attributor import attribute

    store = TraceStore(tmp_path / "s")
    store.save(_calm_trace())
    trace = store.load("calm")
    html = report.render_html(trace, attribute(trace), store=store)
    assert "Token anomalies" not in html


def test_fleet_summary_carries_token_fields(tmp_path):
    burn_dir, calm_dir = tmp_path / "burn", tmp_path / "calm"
    for directory, trace in ((burn_dir, _burn_trace()),
                             (calm_dir, _calm_trace())):
        store = TraceStore(directory)
        store.save(trace)
    summaries = {s.name: s for s in
                 survey([burn_dir, calm_dir])}
    hot = summaries["burn"]
    calm = summaries["calm"]
    assert hot.token_anomalies >= 1
    worst = hot.worst_token_anomaly
    assert worst["tool"] == "search"
    assert worst["tokens"] == 9000
    assert worst["robust_z"] > 3.5
    assert calm.token_anomalies == 0
    assert calm.worst_token_anomaly is None


def test_fleet_json_carries_token_fields(tmp_path, capsys):
    import argparse

    from approximately.cli import cmd_fleet

    burn_dir = tmp_path / "burn"
    store = TraceStore(burn_dir)
    store.save(_burn_trace())
    args = argparse.Namespace(
        stores=[str(burn_dir)], json=True, top_agents=3,
        watch=None, digest_dir=None, iterations=None,
        trend=False, agent=None, fail_on_worsening=False,
        fleet_html=None, webhook=None, alert_anomalies=None,
        alert_worse_than=None, keep_days=30)
    assert cmd_fleet(args) == 0
    payload = json.loads(capsys.readouterr().out)
    entry = payload["stores"][0] if "stores" in payload else payload
    summary = entry.get("summary", entry)
    assert summary["token_anomalies"] >= 1
    assert summary["worst_token_anomaly"]["tokens"] == 9000


def test_store_card_html_shows_burn(tmp_path):
    from approximately.fleet import render_fleet_html

    burn_dir = tmp_path / "burn"
    store = TraceStore(burn_dir)
    store.save(_burn_trace())
    summaries = survey([burn_dir])
    html = render_fleet_html(summaries)
    assert "token burn" in html
    assert "Hardest-working step" in html
