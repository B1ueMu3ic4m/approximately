"""Tests for FM-1.2 (role violation) and FM-1.4 (lost reference) detectors —
these complete 14/14 MAST rule coverage."""

from __future__ import annotations

from approximately.detectors import (
    LostReferenceDetector,
    RoleViolationDetector,
    run_rules,
)
from approximately.trace import TOOL_CALL, Step, Trace

# ---- FM-1.2 RoleViolationDetector -------------------------------------------

def _role_trace() -> Trace:
    trace = Trace(
        task="crew writes and ships the report",
        success=False,
        meta={
            "role_tools": {"writer": ["write_draft", "edit"],
                           "reviewer": ["review_plan"]},
            "agents": {"agent_1": "writer", "agent_2": "reviewer"},
        },
    )
    trace.add(Step(kind="plan", thought="go", meta={"agent": "agent_1"}))
    trace.add(Step(kind=TOOL_CALL, tool="write_draft", args={},
                   result="draft", meta={"agent": "agent_1"}))
    return trace


def test_role_violation_fires_for_out_of_role_tool():
    trace = _role_trace()
    trace.add(Step(kind=TOOL_CALL, tool="send_email", args={},
                   result="sent", meta={"agent": "agent_1"}))
    det = RoleViolationDetector().detect(trace)
    assert det is not None and det.mode_id == "FM-1.2"
    assert det.step_index == 2
    assert "'writer'" in " ".join(det.evidence)


def test_role_violation_silent_for_in_role_tool():
    trace = _role_trace()
    trace.add(Step(kind=TOOL_CALL, tool="edit", args={},
                   result="edited", meta={"agent": "agent_1"}))
    assert RoleViolationDetector().detect(trace) is None


def test_role_violation_silent_without_convention(clean_trace):
    assert RoleViolationDetector().detect(clean_trace) is None


# ---- FM-1.4 LostReferenceDetector -------------------------------------------

def test_lost_reference_fires_on_unknown_confirmation_id():
    trace = Trace(task="book flight", success=False)
    trace.add(Step(kind=TOOL_CALL, tool="book_flight", args={},
                   result="BOOKED #B-1000"))
    trace.add(Step(kind="response",
                   result="Booked! Confirmation #B-9999 confirmed."))
    trace.success = False
    det = LostReferenceDetector().detect(trace)
    assert det is not None and det.mode_id == "FM-1.4"
    assert "#B-9999" in " ".join(det.evidence)


def test_lost_reference_silent_when_id_was_established(clean_trace):
    det = LostReferenceDetector().detect(clean_trace)
    assert det is None


def test_tool_results_may_introduce_new_ids():
    """A tool_call result introducing a brand-new id is legitimate."""
    trace = Trace(task="book", success=True)
    trace.add(Step(kind=TOOL_CALL, tool="book_flight", args={},
                   result="BOOKED #B-NEW-1"))
    assert LostReferenceDetector().detect(trace) is None


# ---- coverage milestone -------------------------------------------------------

def test_rule_coverage_spans_all_categories():
    """Smoke: the rule registry keeps growing, not shrinking."""
    from approximately.detectors import ALL_DETECTORS

    assert len(ALL_DETECTORS) == 14


def test_full_coverage_on_rich_failure_trace():
    """A multi-failure trace surfaces several MAST modes at once."""
    trace = Trace(task="Paris or London? book it", success=False,
                  meta={"ambiguous": True})
    trace.add(Step(kind=TOOL_CALL, tool="book_flight", args={},
                   result="BOOKED #B-1", meta={"mutating": True}))
    trace.add(Step(kind=TOOL_CALL, tool="book_flight", args={},
                   result="BOOKED #B-1", meta={"mutating": True}))
    trace.add(Step(kind="response", result="Booked #B-7777."))
    trace.success = False
    modes = {d.mode_id for d in run_rules(trace)}
    assert "FM-1.3" in modes      # repeats
    assert "FM-3.1" in modes      # failed but claims done
    assert "FM-2.2" in modes      # ambiguous task, no question
