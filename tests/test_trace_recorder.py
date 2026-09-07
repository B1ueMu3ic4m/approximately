import pytest

from approximately.recorder import Recorder, agentstep, current_recorder
from approximately.trace import ERROR, TOOL_CALL, Step, Trace


def test_recorder_captures_steps_and_outcome(clean_trace):
    trace = clean_trace
    assert trace.success is True
    assert len(trace.steps) == 5
    assert trace.steps[1].kind == TOOL_CALL
    assert trace.steps[1].tool == "search_flights"
    assert trace.final_output.startswith("Booked")


def test_recorder_captures_exceptions(store):
    with pytest.raises(ValueError):
        with Recorder("boom", store=store) as rec:
            rec.tool("search", {})
            raise ValueError("exploded")
    assert rec.trace.success is False
    assert rec.trace.steps[-1].kind == ERROR
    assert "ValueError" in rec.trace.steps[-1].error
    assert rec.saved_path is not None  # saved despite the exception
    loaded = store.load(rec.trace.id)
    assert loaded is not None and loaded.success is False


def test_agentstep_records_without_recorder():
    @agentstep
    def add(a, b):
        return a + b

    assert add(2, 3) == 5  # no recorder installed: plain passthrough


def test_agentstep_records_with_recorder():
    @agentstep
    def mul(a, b):
        return a * b

    with Recorder("math", save=False) as rec:
        assert current_recorder() is rec  # installed inside the block
        assert mul(3, 4) == 12
    assert current_recorder() is None  # context exited

    (step,) = rec.trace.tool_calls()
    assert step.tool == "mul"
    assert step.args == {"a": 3, "b": 4}
    assert step.result == "12"


def test_agentstep_records_errors():
    @agentstep
    def divide(a, b):
        return a / b

    with Recorder("math", save=False) as rec:
        try:
            divide(1, 0)
        except ZeroDivisionError:
            pass

    step = rec.trace.steps[-1]
    assert step.kind == TOOL_CALL
    assert "ZeroDivisionError" in step.error


def test_fingerprint_ignores_outcome():
    s1 = Step(kind=TOOL_CALL, tool="t", args={"a": 1}, result="x")
    s2 = Step(kind=TOOL_CALL, tool="t", args={"a": 1}, result="different")
    s3 = Step(kind=TOOL_CALL, tool="t", args={"a": 2}, result="x")
    assert s1.fingerprint() == s2.fingerprint()
    assert s1.fingerprint() != s3.fingerprint()


def test_trace_json_roundtrip(failing_trace):
    clone = Trace.from_json(failing_trace.to_json())
    assert clone.id == failing_trace.id
    assert clone.task == failing_trace.task
    assert len(clone.steps) == len(failing_trace.steps)
    assert clone.steps[-1].to_dict() == failing_trace.steps[-1].to_dict()
