"""Tests for multi-agent conventions and the FM-2.2/FM-2.4/FM-2.5 detectors."""

from __future__ import annotations

from approximately.detectors import (
    ClarificationDetector,
    IgnoredInputDetector,
    WithholdingDetector,
)
from approximately.trace import MESSAGE, TOOL_CALL, Step, Trace


def test_clarification_detector_fires_on_ambiguous_task():
    trace = Trace(task="Book the flight to Paris or London?", success=False)
    trace.add(Step(kind=TOOL_CALL, tool="book_flight",
                   args={"city": "Paris"}, result="BOOKED",
                   meta={"mutating": True}))
    det = ClarificationDetector().detect(trace)
    assert det is not None and det.mode_id == "FM-2.2"
    assert det.step_index == 0


def test_clarification_detector_silent_when_question_asked():
    trace = Trace(task="Paris or London?", success=True)
    trace.add(Step(kind=TOOL_CALL, tool="ask_user",
                   args={}, result="Which city do you prefer?"))
    trace.add(Step(kind=TOOL_CALL, tool="book_flight", args={},
                   result="BOOKED", meta={"mutating": True}))
    assert ClarificationDetector().detect(trace) is None


def test_clarification_detector_silent_on_clear_task(clean_trace):
    assert ClarificationDetector().detect(clean_trace) is None


def test_withholding_detector_fires_when_share_with_never_messaged():
    trace = Trace(task="research then write", success=False)
    trace.add(Step(kind=TOOL_CALL, tool="search", args={},
                   result="key findings: X",
                   meta={"agent": "researcher", "share_with": ["writer"]},
                   index=0))
    trace.add(Step(kind=TOOL_CALL, tool="write_draft", args={},
                   result="draft written",
                   meta={"agent": "writer"}, index=1))
    det = WithholdingDetector().detect(trace)
    assert det is not None and det.mode_id == "FM-2.4"
    assert det.step_index == 0


def test_withholding_detector_silent_when_message_sent():
    trace = Trace(task="research then write", success=False)
    trace.add(Step(kind=TOOL_CALL, tool="search", args={},
                   result="key findings: X",
                   meta={"agent": "researcher", "share_with": ["writer"]}))
    trace.add(Step(kind=MESSAGE, tool="researcher->writer",
                   result="findings: X",
                   meta={"from_agent": "researcher", "to_agent": "writer"}))
    trace.add(Step(kind=TOOL_CALL, tool="write_draft", args={},
                   result="draft", meta={"agent": "writer"}))
    assert WithholdingDetector().detect(trace) is None


def test_ignored_input_detector_fires_on_unacked_message():
    trace = Trace(task="crew run", success=False)
    trace.add(Step(kind=MESSAGE, tool="planner->critic",
                   result="please review this plan",
                   meta={"from_agent": "planner", "to_agent": "critic",
                         "requires_ack": True}))
    det = IgnoredInputDetector().detect(trace)
    assert det is not None and det.mode_id == "FM-2.5"
    assert "never acted" in " ".join(det.evidence)


def test_ignored_input_detector_silent_after_ack_action():
    trace = Trace(task="crew run", success=True)
    trace.add(Step(kind=MESSAGE, tool="planner->critic",
                   result="please review this plan",
                   meta={"from_agent": "planner", "to_agent": "critic",
                         "requires_ack": True, "agent": "planner"}))
    trace.add(Step(kind=TOOL_CALL, tool="review_plan", args={},
                   result="plan approved", meta={"agent": "critic"}))
    assert IgnoredInputDetector().detect(trace) is None


def test_recorder_message_roundtrip(store):
    from approximately.recorder import Recorder

    with Recorder("crew task", store=store) as rec:
        rec.message("planner", "critic", "review please", requires_ack=True)
    loaded = store.load(rec.trace.id)
    (msg,) = [s for s in loaded.steps if s.kind == MESSAGE]
    assert msg.meta["from_agent"] == "planner"
    assert msg.meta["to_agent"] == "critic"
    assert msg.meta["requires_ack"] is True


def test_multiagent_demo_scenario_attributes_withholding():
    from approximately.demo_multiagent import run_demo

    trace, report, _ = run_demo(store_dir=None)
    assert report.failed is True
    modes = {d.mode_id for d in report.detections}
    assert "FM-2.4" in modes   # researcher never messaged the writer
    assert trace.steps[0].meta.get("agent") == "orchestrator"


def test_recorder_step_limit_enables_fm15_budget_detection():
    from approximately.recorder import Recorder

    with Recorder("bounded run", save=False, step_limit=3) as rec:
        for i in range(3):
            rec.tool("do_step", {"i": i}, result=f"ok {i}")
        # budget cut mid-flight: no termination decision was made
    assert rec.trace.meta["step_limit"] == 3
    from approximately.detectors import run_rules

    modes = {d.mode_id for d in run_rules(rec.trace)}
    assert "FM-1.5" in modes
