"""v0.64 — demo --scenario verification: showcase outcome verification."""

from __future__ import annotations

import pytest

from approximately.cli import main
from approximately.demo_verification import run_demo
from approximately.prose import ProseOutcomeVerifyDetector


@pytest.fixture(scope="module")
def verification_demo(tmp_path_factory):
    return run_demo(tmp_path_factory.mktemp("verdemo"))


def test_verification_demo_fires_outcome_verify(verification_demo):
    _, report, path = verification_demo
    sources = [d.source for d in report.detections]
    assert "rule:ProseOutcomeVerifyDetector" in sources
    det = next(d for d in report.detections
               if d.source == "rule:ProseOutcomeVerifyDetector")
    assert det.mode_id == "FM-3.2"
    assert path is not None and path.exists()


def test_verification_scenario_is_an_unchecked_claim(verification_demo):
    # by construction: a resolution claim with zero outcome signals
    # (no "N passed/failed", no traceback) anywhere in the record
    trace, _report, _ = verification_demo
    text = " ".join(s.result for s in trace.steps).lower()
    assert "successfully fixed" in text
    assert "passed" not in text and "failed" not in text
    assert "traceback" not in text


def test_detector_sees_the_claim_directly(verification_demo):
    trace, _, _ = verification_demo
    assert ProseOutcomeVerifyDetector().detect(trace) is not None


def test_cli_demo_verification_scenario(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("APPROXIMATELY_HOME", str(tmp_path))
    assert main(["demo", "--scenario", "verification"]) == 0
    out = capsys.readouterr().out
    assert "recorded demo trace" in out
    assert "rule:ProseOutcomeVerifyDetector" in out
