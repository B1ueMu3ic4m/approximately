from approximately.attributor import attribute
from approximately.taxonomy import OTHER


def test_clean_trace_is_healthy(clean_trace):
    report = attribute(clean_trace)
    assert report.failed is False
    assert report.primary_mode.id == OTHER
    assert "No failure detected" in report.summary
    assert report.judge_used is False and report.disagreement is None


def test_failing_trace_attribution(failing_trace):
    report = attribute(failing_trace)
    assert report.failed is True
    # 3 identical searches (17% of MAST failures) outrank the others
    assert report.primary_mode.id == "FM-1.3"
    assert report.primary_mode.category_name == "Specification & System Design Issues"
    assert len(report.detections) >= 3
    assert any(d.mode_id == "FM-3.2" for d in report.detections)
    assert any(d.mode_id == "FM-3.1" for d in report.detections)
    # fixes are concrete engineering actions, not vibes
    assert report.suggested_fixes and all(fix.strip() for fix in report.suggested_fixes)
    assert any("working state" in fix or "stop condition" in fix
               for fix in report.suggested_fixes)


def test_failed_but_no_detection_falls_back_to_other(store):
    from approximately.recorder import Recorder

    with Recorder("something vague", save=False) as rec:
        rec.tool("do_thing", {}, result="ok")
        rec.fail("mysterious failure")
        rec.observe("stopped trying")  # ends on an observation, not an error
    report = attribute(rec.trace)
    assert report.failed is True
    assert report.primary_mode.id == OTHER
    assert "--judge" in report.summary  # nudges to the LLM judge


def test_judge_unavailable_degrades_gracefully(failing_trace):
    report = attribute(failing_trace, use_judge=True)
    # no openai package configured in this env: rules-only, never a crash
    assert report.primary_mode.id == "FM-1.3"
    assert report.judge_used is False
