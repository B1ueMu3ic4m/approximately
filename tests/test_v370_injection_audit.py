"""v370: every HTML surface holds the injection audit.

Six renderers emit self-contained pages; five of them already
escaped their untrusted strings. ``render_curve_html`` did not —
``curve.trace_id`` rode straight into the page, and a trace id
can be anything (traces are ingested from foreign evidence via
the webhook channel). The audit feeds every renderer hostile
text through its real data path and demands the markers never
appear raw: a script tag stays a script tag only if the page
asked for one, and it never does.
"""

import tempfile

SCRIPT = "<script>alert(1)</script>"
ATTR = '" onmouseover="alert(1)'
EVIL = SCRIPT + ATTR


def _evil_trace(store):
    from approximately.recorder import Recorder

    rec = Recorder(EVIL, store=store)
    rec.tool(SCRIPT, {"cmd": ATTR}, result=EVIL)
    rec.fail(EVIL)
    rec.respond(EVIL, success=False)
    return rec.trace


def _assert_clean(page):
    assert SCRIPT not in page, "a raw script tag reached the page"
    assert ATTR not in page, "a raw attribute breaker reached the page"


def test_fleet_page_escapes_store_name_agents_and_modes():
    from approximately.fleet import StoreSummary, render_fleet_html

    s = StoreSummary(name=EVIL, path=EVIL, traces=1, failed=0,
                     top_agents=[{"agent": SCRIPT, "steps": 1,
                                  "tokens": 5, "errors": 0,
                                  "failure_rate": 0.5}],
                     top_modes=[(SCRIPT, 1)])
    _assert_clean(render_fleet_html([s]))


def test_report_pages_escape_the_recorded_run():
    from approximately.attributor import attribute
    from approximately.report import render_html, render_index_html
    from approximately.store import TraceStore

    store = TraceStore(tempfile.mkdtemp())
    trace = _evil_trace(store)
    report = attribute(trace)
    _assert_clean(render_html(trace, report))
    _assert_clean(render_index_html([(trace, report)]))


def test_replay_page_escapes_recorded_and_replayed():
    from approximately.replayer import ReplayDiff, StepDiff, render_replay_html

    diff = ReplayDiff(trace_id=SCRIPT, steps=[StepDiff(
        index=1, tool=SCRIPT, kind=SCRIPT, recorded=EVIL,
        replayed=EVIL, error=None, similarity=0.5, match=False)],
        match_rate=0.5, verdict=SCRIPT)
    _assert_clean(render_replay_html(diff))


def test_curve_page_escapes_the_trace_id():
    # the v370 fix: trace_id rode into the page raw — traces can
    # be ingested from foreign evidence, so the id is untrusted
    from approximately.curve import BudgetCurve, CurvePoint, render_curve_html

    curve = BudgetCurve(trace_id=EVIL, full_tokens=100,
                        points=[CurvePoint(budget=10,
                                           tokens_used=5,
                                           recall=0.5)])
    page = render_curve_html(curve)
    _assert_clean(page)
    from html import escape
    assert escape(EVIL) in page, \
        "the id still shows up in the page, escaped"


def test_leaderboard_escapes_mode_ids_source_and_dataset():
    from approximately.distill import BenchmarkResult, render_leaderboard_html

    row = {"tp": 1, "fp": 0, "fn": 1, "precision": 0.8,
           "recall": 0.7, "f1": 0.75}
    result = BenchmarkResult(accuracy=0.9, macro_f1=0.8,
                             per_mode={SCRIPT: dict(row)})
    _assert_clean(render_leaderboard_html(result, EVIL, dataset=EVIL))
