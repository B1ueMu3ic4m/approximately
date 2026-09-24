"""v84: runner-up hypotheses rendered in the HTML and Markdown reports.

The CLI (--top), JSON, and MCP payloads carried runner-ups since
v82; the two human-facing renderers were the gap. The card/section
appears only when detectors fired for more than the primary mode.
"""

import html as _html

from approximately.attributor import attribute
from approximately.markdown_report import render_markdown
from approximately.recorder import Recorder
from approximately.report import render_html


def _two_mode_trace():
    rec = Recorder("repair the flaky suite", save=False)
    rec.tool("bash", {"cmd": "pytest -k flaky"}, result="1 failed")
    rec.tool("bash", {"cmd": "pytest -k flaky"}, result="1 failed")
    rec.message("planner", "coder", "please apply the patch",
                requires_ack=True)
    rec.tool("write_draft", {"topic": "patch"}, result="applied")
    rec.respond("gave up", success=False)
    return rec.trace


def test_html_report_shows_runner_up_card():
    trace = _two_mode_trace()
    report = attribute(trace)
    assert report.runner_ups, "fixture must produce runner-ups"
    html = render_html(trace, report)
    assert "Runner-up Hypotheses" in html
    assert "ranking, not an oracle" in html
    for r in report.runner_ups:
        assert r["mode"] in html
        # mode id and label live in separate cells; the label text
        # appears without the id prefix
        name = r["label"][len(r["mode"]):].strip()
        assert _html.escape(name) in html  # cells are escaped


def test_html_report_hides_card_for_single_mode():
    rec = Recorder("clean fail", save=False)
    rec.respond("gave up", success=False)
    html = render_html(rec.trace, attribute(rec.trace))
    assert "Runner-up Hypotheses" not in html


def test_markdown_report_shows_runner_up_section():
    trace = _two_mode_trace()
    report = attribute(trace)
    md = render_markdown(trace, report)
    assert "### Runner-up hypotheses" in md
    for r in report.runner_ups:
        assert f"`{r['mode']}`" in md


def test_markdown_hides_section_for_single_mode():
    rec = Recorder("clean fail", save=False)
    rec.respond("gave up", success=False)
    md = render_markdown(rec.trace, attribute(rec.trace))
    assert "Runner-up" not in md
