import base64
import json

import pytest

from approximately.attributor import attribute
from approximately.regress import render_regression


def test_rendered_test_is_valid_python_and_self_contained(failing_trace):
    report = attribute(failing_trace)
    code = render_regression(failing_trace, report)
    compile(code, "test_approximately.py", "exec")  # must parse

    # trace rides along as base64 — no store needed
    assert "TRACE_B64" in code
    decoded = json.loads(base64.b64decode(
        code.split("TRACE_B64 = (")[1].split(")")[0]
        .replace('"\n    "', "").replace('"', "").replace("\n", "").replace("    ", "")
    ))
    assert decoded["task"] == failing_trace.task


def test_guards_match_attributed_modes(failing_trace):
    report = attribute(failing_trace)
    code = render_regression(failing_trace, report)
    # FM-1.3, FM-3.2, FM-3.1 all fire on this trace -> all guards present
    assert "test_no_repeated_tool_calls" in code
    assert "test_mutating_calls_are_verified" in code
    assert "test_no_premature_termination" in code


def test_generated_guards_fail_on_original_trace(failing_trace, tmp_path):
    """The generated regression file must actually catch the failure."""
    report = attribute(failing_trace)
    code = render_regression(failing_trace, report)
    test_file = tmp_path / "test_regress.py"
    test_file.write_text(code, encoding="utf-8")

    result = pytest.main(["-x", "--no-header", "-q", str(test_file)])
    # the three mode guards must fail against the still-broken trace
    assert result != 0


def test_generated_guards_pass_on_fixed_trace(clean_trace, tmp_path):
    report = attribute(clean_trace)  # healthy -> fallback guard only
    code = render_regression(clean_trace, report)
    test_file = tmp_path / "test_regress_ok.py"
    test_file.write_text(code, encoding="utf-8")

    result = pytest.main(["-x", "--no-header", "-q", str(test_file)])
    assert result == 0
