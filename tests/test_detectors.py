from approximately.detectors import (
    ConversationResetDetector,
    DerailmentDetector,
    MissingVerificationDetector,
    PrematureTerminationDetector,
    RepeatDetector,
    SpecViolationDetector,
    run_rules,
)
from approximately.trace import Step, TOOL_CALL


def test_repeat_detector_fires_on_third_call(failing_trace):
    det = RepeatDetector().detect(failing_trace)
    assert det is not None
    assert det.mode_id == "FM-1.3"
    assert det.step_index == 2  # the first repeated call
    assert len(det.evidence) == 3
    assert det.confidence > 0.6


def test_repeat_detector_silent_on_clean_trace(clean_trace):
    assert RepeatDetector().detect(clean_trace) is None


def test_missing_verification_detector(failing_trace):
    det = MissingVerificationDetector().detect(failing_trace)
    assert det is not None
    assert det.mode_id == "FM-3.2"
    assert det.step_index == 4  # book_flight


def test_missing_verification_satisfied_by_verify_marker(clean_trace):
    assert MissingVerificationDetector().detect(clean_trace) is None


def test_premature_termination_claimed_done_but_failed(failing_trace):
    det = PrematureTerminationDetector().detect(failing_trace)
    assert det is not None
    assert det.mode_id == "FM-3.1"
    assert "marked failed" in " ".join(det.evidence)


def test_premature_termination_silent_on_success(clean_trace):
    assert PrematureTerminationDetector().detect(clean_trace) is None


def test_conversation_reset_detector():
    from approximately.recorder import Recorder

    with Recorder("find flights", save=False) as rec:
        rec.plan("find flights")
        rec.tool("search", {}, result="ok")
        rec.plan("find flights")  # seed prompt re-issued verbatim
    det = ConversationResetDetector().detect(rec.trace)
    assert det is not None and det.mode_id == "FM-2.1"
    assert det.step_index == 2


def test_spec_violation_detector(failing_trace):
    failing_trace.meta["forbidden_tools"] = ["delete_reservation"]
    assert SpecViolationDetector().detect(failing_trace) is None
    step = failing_trace.add(
        Step(kind=TOOL_CALL, tool="delete_reservation", args={"id": "#B-2231"})
    )
    det = SpecViolationDetector().detect(failing_trace)
    assert det is not None and det.step_index == step.index
    assert det.confidence >= 0.9


def test_derailment_detector_needs_enough_calls():
    from approximately.recorder import Recorder

    with Recorder("cook pasta Carbonara", save=False) as rec:
        rec.plan("cook pasta")
        rec.tool("stock_trade", {"ticker": "AAPL"}, result="bought 10")
        rec.tool("upload_photo", {"album": "cats"}, result="ok")
        rec.tool("format_disk", {}, result="done")
    det = DerailmentDetector().detect(rec.trace)
    assert det is not None and det.mode_id == "FM-2.3"


def test_run_rules_sorted_by_confidence(failing_trace):
    detections = run_rules(failing_trace)
    modes = [d.mode_id for d in detections]
    assert "FM-1.3" in modes and "FM-3.2" in modes and "FM-3.1" in modes
    confidences = [d.confidence for d in detections]
    assert confidences == sorted(confidences, reverse=True)
