"""v238: the trends you can see.

A table row is a number; a spike is a picture.  The fleet trend
section gains inline-SVG curves for the slowness, token-burn and
spend day series (the failure-rate curve was already there — the
other three series only had badges), and a trace's token-anomaly
card opens with a bar strip of every tool call's tokens: a retry
loop is a skyline spike, not a footnote.
"""

import time

from approximately.fleet import (
    append_digest,
    digest_snapshot,
    render_fleet_html,
    summarize_trend,
    survey,
    trend_days,
)
from approximately.recorder import Recorder
from approximately.report import render_bars
from approximately.store import TraceStore


def _svg_count(html: str) -> int:
    return html.count("<svg")


def test_render_bars_shape():
    svg = render_bars([1, 2, 3, 90])
    assert svg.startswith("<svg") and svg.count("<rect") == 4
    assert "<title>90</title>" in svg


def test_render_bars_empty_and_single():
    assert render_bars([]) == ""
    assert render_bars([7]).count("<rect") == 1


def test_render_bars_zero_series_is_a_flat_line():
    svg = render_bars([0, 0, 0])
    assert svg.count("<rect") == 3        # 1px stubs, not a divide-by-zero


def _burn_trace(ident):
    from approximately.trace import Step, Trace

    trace = Trace(task=f"{ident} run", id=ident, created_at=1.0,
                  model="gpt-x")
    for tokens, latms in ((110, 38), (95, 41), (105, 40), (90, 42),
                          (100, 39), (115, 40), (85, 41), (120, 40),
                          (108, 42), (92, 40)):
        trace.add(Step(kind="tool_call", tool="search",
                       tokens=tokens, latency_ms=latms))
    trace.add(Step(kind="tool_call", tool="search", tokens=9000,
                   latency_ms=9000))     # burn AND a slowness outlier
    trace.add(Step(kind="response", result="done"))
    return trace


def _trend_summary(tmp_path, with_spend=True):
    burn = tmp_path / "burn"
    store = TraceStore(burn)
    store.save(_burn_trace("loopy"))
    summaries = survey([burn],
                       prices=({"gpt-x": 3.0} if with_spend else None))
    digest = tmp_path / "digest"
    for offset in (2, 1, 0):
        snap = digest_snapshot(summaries)
        snap["ts"] = time.time() - offset * 86400
        append_digest(digest, snap)
    return summarize_trend(trend_days(digest))


def test_trend_section_curves_for_every_series(tmp_path):
    summary = _trend_summary(tmp_path)
    html = render_fleet_html([], trend_summary=summary)
    # failure rate + slowness + token burn + spend
    assert _svg_count(html) >= 4


def test_trend_section_without_spend_has_no_spend_curve(tmp_path):
    summary = _trend_summary(tmp_path, with_spend=False)
    html = render_fleet_html([], trend_summary=summary)
    assert "spend:" not in html
    assert _svg_count(html) >= 3


def test_token_card_opens_with_a_bar_strip(tmp_path):
    from approximately.attributor import attribute
    from approximately.report import render_html

    trace = _burn_trace("loopy")
    html = render_html(trace, attribute(trace))
    card_pos = html.find("Token anomalies")
    strip_pos = html.find('aria-label="bar chart"', card_pos)
    assert card_pos != -1 and strip_pos != -1
    assert strip_pos - card_pos < 400    # the strip leads the card


def test_quiet_trace_has_no_bar_strip():
    from approximately.attributor import attribute
    from approximately.report import render_html

    rec = Recorder("calm", save=False)
    rec.tool("search", {}, tokens=50)
    rec.respond("done", success=True)
    html = render_html(rec.trace, attribute(rec.trace))
    assert 'aria-label="bar chart"' not in html
