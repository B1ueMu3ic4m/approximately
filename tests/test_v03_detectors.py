"""Tests for the v0.3.0 detectors (FM-1.5, FM-2.6, FM-3.3),
the export-dataset command, and the langgraph on_llm_start callback."""

from __future__ import annotations

import json

import pytest

from approximately.detectors import (
    NoTerminationDetector,
    ReasoningActionMismatchDetector,
    WeakVerificationDetector,
    run_rules,
)
from approximately.trace import Step, TOOL_CALL, Trace


# ---- FM-1.5 NoTerminationDetector -------------------------------------------

def _call(tool: str, args: dict, index: int = 0, result: str = "r") -> Step:
    return Step(kind=TOOL_CALL, tool=tool, args=args, result=result)


def test_long_range_loop_fires_fm15():
    trace = Trace(task="book flight", success=False)
    trace.add(Step(kind="plan", thought="go"))
    trace.add(_call("search", {"q": "1"}))
    for i in range(2, 8):  # filler steps break the local repeat window
        trace.add(Step(kind="plan", thought=f"waiting {i}"))
    trace.add(_call("search", {"q": "1"}))
    trace.add(_call("search", {"q": "1"}))
    det = NoTerminationDetector().detect(trace)
    assert det is not None and det.mode_id == "FM-1.5"
    assert det.step_index == len(trace.steps) - 1  # the last identical call


def test_budget_exhaustion_midflight_fires_fm15():
    trace = Trace(task="long task", success=False,
                  meta={"step_limit": 4})
    trace.add(Step(kind="plan", thought="go"))
    trace.add(_call("search", {"a": 1}))
    trace.add(_call("search", {"a": 2}))
    trace.add(_call("search", {"a": 3}))
    det = NoTerminationDetector().detect(trace)
    assert det is not None and det.mode_id == "FM-1.5"
    assert "step limit 4" in " ".join(det.evidence)


def test_local_repeat_does_not_trigger_fm15(clean_trace):
    """Local repeats belong to FM-1.3; FM-1.5 must stay silent here."""
    assert NoTerminationDetector().detect(clean_trace) is None


# ---- FM-2.6 ReasoningActionMismatchDetector ---------------------------------

def test_announced_tool_mismatch_fires_fm26():
    trace = Trace(task="book", success=False)
    trace.add(Step(kind=TOOL_CALL, tool="search_flights",
                   args={"q": "SFO"},
                   thought="Great, I will now call book_flight to reserve.",
                   index=0))
    det = ReasoningActionMismatchDetector().detect(trace)
    assert det is not None and det.mode_id == "FM-2.6"
    assert det.step_index == 0


def test_matching_announcement_is_silent():
    trace = Trace(task="book", success=True)
    trace.add(Step(kind=TOOL_CALL, tool="search_flights",
                   args={"q": "SFO"}, result="JT-044",
                   thought="I will now call search_flights to find options.",
                   index=0))
    assert ReasoningActionMismatchDetector().detect(trace) is None


# ---- FM-3.3 WeakVerificationDetector ----------------------------------------

def test_echo_verification_fires_fm33():
    trace = Trace(task="book", success=True)
    trace.add(Step(kind=TOOL_CALL, tool="book_flight", args={},
                   result="BOOKED #B-2231", meta={"mutating": True}, index=0))
    trace.add(Step(kind=TOOL_CALL, tool="verify_booking", args={},
                   result="BOOKED #B-2231", index=1))
    det = WeakVerificationDetector().detect(trace)
    assert det is not None and det.mode_id == "FM-3.3"
    assert det.step_index == 1


def test_independent_verification_is_silent(clean_trace):
    """clean_trace's verify returns different text than the booking claim."""
    assert WeakVerificationDetector().detect(clean_trace) is None


def test_no_verification_stays_fm32_not_fm33(failing_trace):
    assert WeakVerificationDetector().detect(failing_trace) is None
    modes = [d.mode_id for d in run_rules(failing_trace)]
    assert "FM-3.2" in modes and "FM-3.3" not in modes


# ---- attribution integration ------------------------------------------------

def test_new_detectors_rank_correctly_against_fm13(failing_trace):
    report = __import__("approximately.attributor", fromlist=["attribute"]).attribute(failing_trace)
    # the trace has no long-range loop, no intent mismatch, no echo verify:
    # the new detectors must not hijack the verdict
    assert report.primary_mode.id == "FM-1.3"


# ---- export-dataset CLI ------------------------------------------------------

def test_export_dataset_command(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("APPROXIMATELY_HOME", str(tmp_path / "traces"))
    from approximately.cli import main

    main(["demo"])
    out = tmp_path / "dataset.jsonl"
    code = main(["export-dataset", "-o", str(out)])
    payload = capsys.readouterr().out
    assert code == 0
    assert "wrote 1 labeled traces" in payload
    record = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert record["label"] == "FM-1.3"
    assert record["task"].startswith("Find the cheapest")


# ---- langgraph on_llm_start --------------------------------------------------

def test_langgraph_handler_records_completion_style_llm_calls():
    pytest.importorskip("langchain_core")
    from approximately.contrib.langgraph import ApproximatelyCallbackHandler

    handler = ApproximatelyCallbackHandler("completion run")
    handler.on_llm_start({"name": "gpt"}, ["summarize this please"], run_id="r1")
    plans = [s for s in handler.recorder.trace.steps if s.kind == "plan"]
    assert len(plans) == 1
    assert "summarize this" in plans[0].thought
