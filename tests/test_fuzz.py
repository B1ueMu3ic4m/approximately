"""Randomized (fuzz) tests: detectors and attribution must uphold invariants
on arbitrary traces — never crash, never fabricate evidence, stay
deterministic."""

from __future__ import annotations

import random

import pytest

from approximately.attributor import attribute
from approximately.detectors import run_rules
from approximately.taxonomy import FAILURE_MODES
from approximately.trace import PLAN, RESPONSE, TOOL_CALL, Step, Trace

TOOLS = ["search", "book", "verify_booking", "cancel", "email", "pay"]
WORDS = ["flight", "hotel", "seat", "cheap", "SFO", "NRT", "refund", "12A"]

rng = random.Random(20260908)  # deterministic seed: reproducible failures


def _random_args() -> dict:
    return {
        rng.choice(["origin", "target", "id", "q"]): rng.choice(WORDS),
        "n": rng.randint(0, 5),
    }


def _random_trace(success: bool, force_repeat: bool = False) -> Trace:
    trace = Trace(task=f"book a {rng.choice(WORDS)} under $900", success=success)
    trace.add(Step(kind=PLAN, thought="do the task"))
    last_tool = None
    for i in range(rng.randint(1, 12)):
        if force_repeat and 1 <= i <= 2:
            step = Step(kind=TOOL_CALL, tool=last_tool[0], args=last_tool[1],
                        result="same")
        elif rng.random() < 0.75:
            tool = rng.choice(TOOLS)
            args = _random_args()
            last_tool = (tool, args)
            error = "TimeoutError: upstream" if rng.random() < 0.15 else None
            step = Step(kind=TOOL_CALL, tool=tool, args=args,
                        result=f"result {rng.randint(0, 9)}", error=error,
                        meta={"mutating": rng.random() < 0.3})
        else:
            step = Step(kind=PLAN, thought=f"thinking about {rng.choice(WORDS)}")
        trace.add(step)
    trace.add(Step(kind=RESPONSE, result="final answer",
                   error=None if success else "task failed"))
    return trace


def test_fuzz_rules_never_crash_and_invariants_hold():
    for _ in range(300):
        trace = _random_trace(success=rng.random() < 0.5)
        detections = run_rules(trace)
        for det in detections:
            assert 0.0 <= det.confidence <= 1.0, det
            assert det.evidence, f"{det.mode_id} fired without evidence"
            assert det.mode_id in FAILURE_MODES
            assert 0 <= det.step_index < len(trace.steps)


def test_fuzz_report_always_yields_valid_primary():
    for _ in range(300):
        report = attribute(_random_trace(success=rng.random() < 0.5))
        assert report.primary_mode.id in FAILURE_MODES
        assert report.summary
        assert isinstance(report.suggested_fixes, list)


def test_fuzz_deterministic_same_input_same_output():
    trace = _random_trace(success=False, force_repeat=True)
    a = [(d.mode_id, d.step_index, d.confidence, tuple(d.evidence))
         for d in run_rules(trace)]
    b = [(d.mode_id, d.step_index, d.confidence, tuple(d.evidence))
         for d in run_rules(trace)]
    assert a == b
    ra, rb = attribute(trace), attribute(trace)
    assert ra.to_dict() == rb.to_dict()


def test_fuzz_clean_success_traces_never_flag_verification_or_termination():
    """A successful run with verified mutations must not be called premature
    or unverified."""
    for _ in range(100):
        with_result = "ok"
        trace = Trace(task="find flight SFO NRT and book", success=True)
        trace.add(Step(kind=PLAN, thought="search then book then verify"))
        trace.add(Step(kind=TOOL_CALL, tool="search", args={"q": "SFO NRT"},
                       result="JT-044 $870"))
        trace.add(Step(kind=TOOL_CALL, tool="book", args={"seat": "12A"},
                       result="BOOKED #1", meta={"mutating": True}))
        trace.add(Step(kind=TOOL_CALL, tool="verify_booking", args={"id": "#1"},
                       result="confirmed"))
        trace.add(Step(kind=RESPONSE, result=with_result))
        detections = run_rules(trace)
        assert not [d for d in detections if d.mode_id in ("FM-3.1", "FM-3.2")]


@pytest.mark.parametrize("n_steps", [0, 1, 2])
def test_tiny_traces_do_not_crash(n_steps):
    trace = Trace(task="minimal", success=False if n_steps == 0 else None)
    for i in range(n_steps):
        trace.add(Step(kind=TOOL_CALL, tool="t", args={}, result="r"))
    report = attribute(trace)
    assert report.primary_mode.id in FAILURE_MODES


def test_empty_trace_report_is_healthy():
    report = attribute(Trace(task="nothing happened", success=True))
    assert "No failure detected" in report.summary
