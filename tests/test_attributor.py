import pytest

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


# ---- Bayesian evidence fusion (LLR pool) ------------------------------------

def test_fusion_prior_orders_base_rates_when_evidence_is_equal():
    """With identical weak evidence, the more common MAST mode ranks first."""
    from approximately.attributor import fuse_evidence
    from approximately.detectors import Detection

    def weak(mode):
        return Detection(mode_id=mode, step_index=0, confidence=0.51,
                         evidence=["e"], source="test")
    ranked = fuse_evidence([weak("FM-3.1"), weak("FM-1.3")])
    assert ranked[0].mode_id == "FM-1.3"   # 17.14% share outranks 7.82%


def test_fusion_near_certain_evidence_beats_strong_prior():
    """Bayesian base-rate correction, honestly tested.

    A 0.9-confidence FM-1.1 does NOT beat a 0.8-confidence FM-1.3: the 17x
    base-rate gap is worth ~2.9 nats and the confidence gap only ~0.8. That
    is correct base-rate correction, not a bug. Conclusive (1.0) evidence —
    a hard constraint check like a declared-forbidden-tool hit — does win.
    """
    from approximately.attributor import fuse_evidence
    from approximately.detectors import Detection

    assert fuse_evidence([
        Detection(mode_id="FM-1.3", step_index=1, confidence=0.8,
                  evidence=["repeats"], source="test"),
        Detection(mode_id="FM-1.1", step_index=0, confidence=0.9,
                  evidence=["forbidden tool"], source="test"),
    ])[0].mode_id == "FM-1.3"  # 0.9 vs 0.8: base rate wins

    near_certain = Detection(mode_id="FM-1.1", step_index=0, confidence=1.0,
                             evidence=["forbidden tool"], source="test")
    ranked = fuse_evidence([
        Detection(mode_id="FM-1.3", step_index=1, confidence=0.8,
                  evidence=["repeats"], source="test"),
        near_certain,
    ])
    assert ranked[0].mode_id == "FM-1.1"   # conclusive evidence beats prior


def test_fusion_accumulates_independent_evidence():
    """Two independent 0.6 detections of one mode outrank one 0.6 of another
    with an identical prior position — additive log-space accumulation."""
    from approximately.attributor import fuse_evidence
    from approximately.detectors import Detection

    a1 = Detection(mode_id="FM-3.2", step_index=0, confidence=0.6,
                   evidence=["e1"], source="t")
    a2 = Detection(mode_id="FM-3.2", step_index=1, confidence=0.6,
                   evidence=["e2"], source="t")
    b = Detection(mode_id="FM-1.5", step_index=2, confidence=0.6,
                  evidence=["e3"], source="t")
    ranked = fuse_evidence([a1, a2, b])
    assert ranked[0].mode_id == "FM-3.2"   # LLRs accumulate for FM-3.2


def test_fusion_confidence_zero_is_evidence_against():
    """c=0 must count AGAINST a mode (smoothed logit), not be neutral."""
    import math

    from approximately.attributor import _llr

    assert _llr(0.0) < 0 < _llr(1.0)      # signed, bounded both ends
    assert _llr(1.0) == pytest.approx(math.log(1.005 / 0.005))
