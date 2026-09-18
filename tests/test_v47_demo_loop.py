"""v0.47 — demo --scenario loop: showcase cycle-grade repetition."""

from __future__ import annotations

import pytest

from approximately.cli import main
from approximately.demo_loop import run_demo
from approximately.detectors import CycleRepeatDetector, RepeatDetector


@pytest.fixture(scope="module")
def loop_demo(tmp_path_factory):
    return run_demo(tmp_path_factory.mktemp("loopdemo"))


def test_loop_demo_fires_cycle_detector(loop_demo):
    _, report, path = loop_demo
    sources = [d.source for d in report.detections]
    assert "rule:CycleRepeatDetector" in sources
    cycle = next(d for d in report.detections
                 if d.source == "rule:CycleRepeatDetector")
    text = " ".join(str(e) for e in cycle.evidence)
    assert "planner -> navigator -> editor" in text
    assert path is not None and path.exists()


def test_loop_demo_exact_fingerprint_stays_quiet(loop_demo):
    # args evolve every turn — the whole point of the scenario
    trace, _, _ = loop_demo
    assert RepeatDetector().detect(trace) is None
    assert CycleRepeatDetector().detect(trace) is not None


def test_cli_demo_loop_scenario(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("APPROXIMATELY_HOME", str(tmp_path))
    assert main(["demo", "--scenario", "loop"]) == 0
    out = capsys.readouterr().out
    assert "recorded demo trace" in out
    assert "rule:CycleRepeatDetector" in out
