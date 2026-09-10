"""Minimal-repair search: prescription validation by re-attribution."""

from __future__ import annotations

import pytest

from approximately.attributor import attribute
from approximately.recorder import Recorder
from approximately.repair import plan_repair
from approximately.trace import TOOL_CALL


def _booking_trace():
    with Recorder("booking failure", save=False) as rec:
        rec.plan("search and book")
        rec.tool("search", {"q": "SFO"}, result="JT-044")
        rec.tool("search", {"q": "SFO"}, result="JT-044")     # FM-1.3
        rec.tool("book", {"seat": "12A"}, result="BOOKED", mutating=True)
        rec.respond("done", success=False)                     # FM-3.1
    return rec.trace


def test_repair_clears_repeat_and_verification_modes():
    result = plan_repair(_booking_trace())
    assert result.repaired
    assert "FM-1.3" in result.cleared_modes
    assert "FM-3.2" in result.cleared_modes
    assert any("drop-duplicate" in a for a in result.applied)
    assert any("insert-verify" in a for a in result.applied)


def test_premature_termination_reported_unrepairable():
    """FM-3.1 needs an agent-level change; trace surgery must not fake it."""
    result = plan_repair(_booking_trace())
    assert "FM-3.1" in result.unrepairable
    assert result.summary()


def test_repaired_trace_passes_its_own_guards():
    """The repaired trace would survive the generated regression guards."""
    from approximately.detectors import run_rules

    result = plan_repair(_booking_trace())
    modes = {d.mode_id for d in run_rules(result.repaired_trace)}
    assert "FM-1.3" not in modes
    assert "FM-3.2" not in modes
    # every mutating call is now verified
    steps = result.repaired_trace.steps
    for i, step in enumerate(steps):
        if step.kind == TOOL_CALL and step.meta.get("mutating"):
            assert any(_is_verify(steps[i + 1:])
                       for _ in [0]), f"unverified: {step.tool}"


def _is_verify(steps):
    return any(
        s.meta.get("verify") or (s.kind == TOOL_CALL and s.tool and
        any(m in s.tool.lower() for m in ("verify", "check", "get_")))
        for s in steps)


def test_clean_trace_needs_no_repair(clean_trace):
    result = plan_repair(clean_trace)
    assert not result.applied
    assert not result.repaired
    assert result.summary() == ""


def test_repair_is_deterministic(failing_trace):
    a, b = plan_repair(failing_trace), plan_repair(failing_trace)
    assert a.applied == b.applied
    assert a.cleared_modes == b.cleared_modes
