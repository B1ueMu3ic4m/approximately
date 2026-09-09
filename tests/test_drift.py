"""Behavior-drift detection: PSI over action structure tokens."""

from __future__ import annotations

from approximately.drift import detect_drift, population_stability
from approximately.recorder import Recorder


def _run(actions, task="drift probe"):
    with Recorder(task, save=False) as rec:
        for tool, args in actions:
            rec.tool(tool, args, result="ok")
        rec.respond("done", success=True)
    return rec.trace


def test_identical_distributions_zero_psi():
    baseline = [_run([("search", {"q": i}), ("book", {"id": i})])
                for i in range(5)]
    current = [_run([("search", {"q": i + 100}), ("book", {"id": i + 100})])
               for i in range(5)]
    report = detect_drift(baseline, current)
    # same shape, different values: structure tokens identical -> PSI ~ 0
    assert report.psi < 0.01
    assert report.verdict == "no shift"


def test_disjoint_distributions_significant_psi():
    baseline = [_run([("search", {"q": i}), ("book", {"id": i})])
                for i in range(5)]
    current = [_run([("email", {"to": i}), ("pay", {"amt": i})])
               for i in range(5)]
    report = detect_drift(baseline, current)
    assert report.psi > 0.25
    assert report.verdict == "significant shift"
    assert report.top_shifted, "largest moves are reported"
    actions = {a for a, _, _ in report.top_shifted}
    assert "tool_call:email {to}" in actions


def test_psi_symmetric():
    forward = population_stability(
        dict.fromkeys(("tool_call:search {q}", "tool_call:book {}"), 1),
        dict.fromkeys(("tool_call:email {to}", "tool_call:pay {amt}"), 1))
    backward = population_stability(
        dict.fromkeys(("tool_call:email {to}", "tool_call:pay {amt}"), 1),
        dict.fromkeys(("tool_call:search {q}", "tool_call:book {}"), 1))
    # PSI formula (a-b)ln(a/b) is symmetric; empty-bucket smoothing breaks
    # exact symmetry slightly, so compare with tolerance
    assert abs(forward[0] - backward[0]) < 0.1


def test_smoothing_handles_disjoint_buckets():
    baseline = [_run([("only_old_tool", {}), ("another_old", {})])]
    current = [_run([("brand_new_tool", {}), ("another_new", {})])]
    report = detect_drift(baseline, current)
    assert report.psi > 0.25  # EPS keeps this finite, not inf


def test_empty_windows_are_handled():
    report = detect_drift([], [])
    assert report.verdict == "no shift"


def test_cli_drift(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("APPROXIMATELY_HOME", str(tmp_path / "t"))
    from approximately.cli import main

    main(["demo"])
    main(["demo"])
    code = main(["drift"])
    out = capsys.readouterr().out
    assert code == 0
    assert "PSI" in out
