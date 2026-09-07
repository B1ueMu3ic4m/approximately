"""Regression-test generator under adversarial content + performance smoke."""

from __future__ import annotations

import base64
import json
import time

import pytest

from approximately.attributor import attribute
from approximately.regress import render_regression
from approximately.trace import Step, TOOL_CALL, Trace


ADVERSARIAL_TASK = (
    'task with """triple quotes""", \\backslashes\\, \n newlines, '
    "{braces}, ${shell}, unicode ✈️ 日本語, and 'quotes'"
)


def _adversarial_trace() -> Trace:
    trace = Trace(task=ADVERSARIAL_TASK, success=False)
    trace.add(Step(kind="plan", thought='plan "quoted" \\raw\\ {json}'))
    trace.add(Step(kind=TOOL_CALL, tool='tool"quote', args={"k": "<&>\n"},
                   result='result with " and \\ and \n'))
    trace.add(Step(kind=TOOL_CALL, tool='tool"quote', args={"k": "<&>\n"},
                   result='result with " and \\ and \n'))
    trace.add(Step(kind=TOOL_CALL, tool="book", args={}, result="BOOKED",
                   meta={"mutating": True}))
    trace.add(Step(kind="response", result='done "quoted"'))
    trace.success = False
    return trace


def test_adversarial_trace_generates_compilable_test():
    trace = _adversarial_trace()
    code = render_regression(trace, attribute(trace))
    compile(code, "adversarial_test.py", "exec")


def test_adversarial_trace_embed_roundtrips():
    trace = _adversarial_trace()
    code = render_regression(trace, attribute(trace))
    b64 = code.split("TRACE_B64 = (")[1].split(")")[0]
    b64 = b64.replace('"', "").replace("\n", "").replace("    ", "")
    decoded = json.loads(base64.b64decode(b64))
    assert decoded["task"] == ADVERSARIAL_TASK
    assert Trace.from_dict(decoded).steps[1].tool == 'tool"quote'


def test_generated_guards_catch_adversarial_repeat(tmp_path):
    trace = _adversarial_trace()
    code = render_regression(trace, attribute(trace))
    test_file = tmp_path / "test_adv.py"
    test_file.write_text(code, encoding="utf-8")
    result = pytest.main(["-q", "--no-header", "-x",
                          str(test_file), "-k", "repeated"])
    assert result != 0  # the FM-1.3 guard must catch it


# ---- performance ------------------------------------------------------------

def _long_trace(n_steps: int) -> Trace:
    trace = Trace(task="long running agent", success=False)
    trace.add(Step(kind="plan", thought="loop"))
    for i in range(n_steps):
        trace.add(Step(
            kind=TOOL_CALL,
            tool="search",
            args={"q": f"query-{i % 50}"},
            result=f"result {i} with some payload text " * 3,
            meta={"mutating": i % 10 == 0},
        ))
    trace.add(Step(kind="response", result="done"))
    trace.success = False
    return trace


def test_attribution_performance_5k_steps():
    trace = _long_trace(5000)
    start = time.perf_counter()
    report = attribute(trace)
    elapsed = time.perf_counter() - start
    assert report.primary_mode.id == "FM-3.1"
    assert elapsed < 5.0, f"attribution took {elapsed:.2f}s"


def test_forecast_performance_5k_steps():
    trace = _long_trace(5000)
    from approximately.context import default_facts, forecast

    start = time.perf_counter()
    fc = forecast(trace, budget=2000, facts=default_facts(trace))
    elapsed = time.perf_counter() - start
    assert fc.evicted_count > 0
    assert elapsed < 5.0, f"forecast took {elapsed:.2f}s"
