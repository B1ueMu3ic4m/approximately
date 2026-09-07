"""HTML report hardening: injection escaping, meta pollution, validity on
adversarial traces."""

from __future__ import annotations

from approximately.attributor import attribute
from approximately.recorder import Recorder
from approximately.report import render_html


def _evil_trace() -> Recorder:
    rec = Recorder(
        task="exfil <script>alert('task')</script> & <img src=x onerror=alert(2)>",
        model="evil-model\"><script>",
        save=False,
    )
    rec.plan("normal plan")
    rec.tool("evil_tool", {"cmd": "<script>alert(3)</script>"},
             result="<script>alert(4)</script> \"quotes\" 'single' </script>",
             thought="`backticks` & ampersands <b>bold</b>")
    rec.respond("<svg onload=alert(5)>done", success=False)
    return rec


def test_report_escapes_every_injection_vector():
    rec = _evil_trace()
    report = attribute(rec.trace)
    html = render_html(rec.trace, report)
    for raw in ("<script>", "<img src=x", "<svg onload="):
        assert raw not in html, f"unescaped injection: {raw}"
    assert "&lt;script&gt;" in html
    assert "&amp;" in html


def test_report_does_not_pollute_trace_meta():
    rec = _evil_trace()
    before = {id(s): dict(s.meta) for s in rec.trace.steps}
    render_html(rec.trace, attribute(rec.trace))
    after = {id(s): dict(s.meta) for s in rec.trace.steps}
    assert before == after, "render_html must not mutate step meta"


def test_report_valid_structure_on_empty_trace():
    from approximately.trace import Trace

    trace = Trace(task="empty", success=True)
    html = render_html(trace, attribute(trace))
    assert html.startswith("<!doctype html>")
    assert html.rstrip().endswith("</html>")


def test_report_highlights_only_evidence_steps(failing_trace, clean_trace):
    from approximately.attributor import attribute as attr

    html_bad = render_html(failing_trace, attr(failing_trace))
    assert 'class="hot"' in html_bad
    html_good = render_html(clean_trace, attr(clean_trace))
    assert 'class="hot"' not in html_good
