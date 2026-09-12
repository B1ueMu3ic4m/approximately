"""Streaming reliability monitor: signals, level machine, escalation."""

from __future__ import annotations

import pytest

from approximately.precursor import mine
from approximately.recorder import Recorder
from approximately.streaming import Level, StreamingMonitor
from approximately.trace import Trace


def _live(actions):
    """Record actions one by one, yielding (trace, step) as we go."""
    with Recorder("live probe", save=False) as rec:
        for tool, args, kwargs in actions:
            rec.tool(tool, args, **kwargs)
            yield rec.trace


# ---- repetition signal ---------------------------------------------------------

def test_repetition_velocity_rises_with_identical_calls():
    monitor = StreamingMonitor()
    risks = []
    for i in range(4):
        with Recorder(f"run {i}", save=False) as rec:
            rec.tool("search", {"q": 1}, result="same")
            risks.append(monitor.observe(rec.trace).signals["repetition"])
    assert risks == [0.0, 0.5, 1.0, 1.0]  # 1st no, 2nd half, 3rd+ saturated


def test_sliding_window_forgets_old_calls():
    monitor = StreamingMonitor(window=3)
    with Recorder("windowed", save=False) as rec:
        rec.tool("a", {}, result="1")
        monitor.observe(rec.trace)
        rec.tool("b", {}, result="2")
        monitor.observe(rec.trace)
        rec.tool("c", {}, result="3")
        monitor.observe(rec.trace)
        # "a" left the window: its recurrence is forgotten
        rec.tool("a", {}, result="4")
        state = monitor.observe(rec.trace)
    assert state.signals["repetition"] == 0.0


# ---- verification debt ------------------------------------------------------------

def test_verification_debt_accumulates_and_clears():
    monitor = StreamingMonitor(verification_debt_limit=3)
    with Recorder("debt", save=False) as rec:
        rec.tool("write_a", {}, result="ok", mutating=True)
        s1 = monitor.observe(rec.trace)
        rec.tool("write_b", {}, result="ok", mutating=True)
        s2 = monitor.observe(rec.trace)
        rec.tool("get_state", {}, result="ok", meta={"verify": True})
        s3 = monitor.observe(rec.trace)
    assert s1.signals["verification_debt"] == pytest.approx(1 / 3)
    assert s2.signals["verification_debt"] == pytest.approx(2 / 3)
    assert s3.signals["verification_debt"] == pytest.approx(1 / 3)


# ---- level machine -------------------------------------------------------------------

def test_levels_cascade_with_risk():
    monitor = StreamingMonitor(watch_at=0.3, elevated_at=0.55,
                               critical_at=0.8)
    assert monitor._level_for(0.0) == Level.NOMINAL
    assert monitor._level_for(0.4) == Level.WATCH
    assert monitor._level_for(0.6) == Level.ELEVATED
    assert monitor._level_for(0.9) == Level.CRITICAL


def test_hysteresis_prevents_flapping():
    monitor = StreamingMonitor(watch_at=0.3, elevated_at=0.55,
                               critical_at=0.8, hysteresis=0.1)
    monitor._last_level = Level.ELEVATED
    # risk dips just below elevated_at but within hysteresis: stays ELEVATED
    assert monitor._level_for(0.5) == Level.ELEVATED
    # a real drop below the watch floor leaves the level entirely
    assert monitor._level_for(0.2) == Level.NOMINAL
    # watch-level hysteresis: from WATCH, 0.25 still holds WATCH
    monitor._last_level = Level.WATCH
    assert monitor._level_for(0.25) == Level.WATCH


# ---- escalation ------------------------------------------------------------------------

def test_escalation_fires_once_per_crossing():
    monitor = StreamingMonitor(window=3, repetition_threshold=1,
                               repetition_weight=1.0,
                               elevated_at=0.4)
    observations = []
    for i in range(4):
        with Recorder(f"loop {i}", save=False) as rec:
            rec.tool("search", {"q": 1}, result="r")
            observations.append(monitor.observe(rec.trace))
    escalations = [s.escalated for s in observations]
    assert escalations[0] is False
    assert escalations.count(True) == 1  # fired on the first crossing only


def test_precursor_model_integration():
    """A mined precursor model raises risk on matching prefixes."""
    bad = []
    for i in range(10):
        with Recorder(f"bad {i}", save=False) as rec:
            rec.tool("arm", {"i": i}, result="x")
            rec.tool("detonate", {}, error="boom")
            rec.fail("boom")
        bad.append(rec.trace)
    for i in range(10):
        with Recorder(f"safe {i}", save=False) as rec:
            rec.tool("walk", {"i": i}, result="x")
            rec.respond("ok", success=True)
        bad.append(rec.trace)
    model = mine(bad)

    monitor = StreamingMonitor(precursor_model=model,
                               precursor_weight=0.8,
                               elevated_at=0.4)
    with Recorder("live", save=False) as rec:
        rec.tool("arm", {"i": 99}, result="x")
        rec.tool("detonate", {}, error="about to")
        state = monitor.observe(rec.trace)
    assert state.signals["precursor"] > 0.3
    assert state.level in (Level.ELEVATED, Level.CRITICAL)


def test_no_steps_is_safe():
    monitor = StreamingMonitor()
    state = monitor.observe(Trace(task="empty", success=True))
    assert state.step_index == -1 and state.risk == 0.0


def test_risk_curve_is_recorded():
    monitor = StreamingMonitor()
    with Recorder("curve", save=False) as rec:
        rec.tool("a", {}, result="1")
        monitor.observe(rec.trace)
        rec.tool("b", {}, result="2")
        monitor.observe(rec.trace)
    curve = monitor.risk_curve()
    assert [i for i, _ in curve] == [0, 1]
    assert all(0.0 <= r <= 1.0 for _, r in curve)
