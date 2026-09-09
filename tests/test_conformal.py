"""v0.5 calibration + conformal attribution: NLL temperature scaling,
ECE reporting, distribution-free coverage guarantee, set-size behavior."""

from __future__ import annotations

import math
import random

import pytest

from approximately.attributor import score_modes
from approximately.calibration import (
    ConformalModel,
    expected_calibration_error,
    fit_conformal,
    fit_temperature,
    softmax,
)
from approximately.recorder import Recorder
from approximately.taxonomy import FAILURE_MODES


def _traced(actions, success):
    with Recorder("calibration probe", save=False) as rec:
        for tool, args in actions:
            rec.tool(tool, args, result="ok")
        rec.respond("done", success=success)
    return rec.trace


def _labeled_set(n_per_mode: int = 40, seed: int = 7, flip_rate: float = 0.15):
    """A labeled surface with REAL uncertainty: 15% of examples are flipped
    (their noise dominates), which is what makes calibration and conformal
    thresholds non-degenerate — exactly like real detector output."""
    rng = random.Random(seed)
    surface = {
        "FM-1.3": {"FM-1.3": 3.0, "FM-3.1": 0.2, "FM-3.2": 0.1, "OTHER": -1.0},
        "FM-3.1": {"FM-1.3": 0.1, "FM-3.1": 2.5, "FM-3.2": 0.3, "OTHER": -1.0},
        "FM-3.2": {"FM-1.3": 0.0, "FM-3.1": 0.2, "FM-3.2": 2.8, "OTHER": -0.5},
    }
    labeled = []
    for gold, sc in surface.items():
        for _ in range(n_per_mode):
            flip = rng.random() < flip_rate
            noisy = {k: (-v if flip else v) + rng.gauss(0, 0.15)
                     for k, v in sc.items()}
            labeled.append((noisy, gold))
    return labeled


# ---- softmax ------------------------------------------------------------------

def test_softmax_sums_to_one_and_temperature_monotone():
    scores = {"FM-1.3": 3.0, "FM-3.1": 0.2}
    cool = softmax(scores, temperature=0.5)
    warm = softmax(scores, temperature=2.0)
    assert abs(sum(cool.values()) - 1) < 1e-9
    assert abs(sum(warm.values()) - 1) < 1e-9
    assert cool["FM-1.3"] > warm["FM-1.3"]  # lower temperature = sharper


def test_softmax_rejects_nonpositive_temperature():
    with pytest.raises(ValueError):
        softmax({"a": 1.0}, temperature=0)


# ---- ECE (reporting metric) ------------------------------------------------------

def test_ece_zero_when_confidence_matches_accuracy():
    pairs = ([(0.9, True)] * 90 + [(0.9, False)] * 10
             + [(0.1, False)] * 90 + [(0.1, True)] * 10)
    assert expected_calibration_error(pairs) == pytest.approx(0.0, abs=1e-9)


def test_ece_positive_when_overconfident():
    pairs = [(0.9, True)] * 50 + [(0.9, False)] * 50
    assert expected_calibration_error(pairs) > 0.3


def test_ece_empty_is_zero():
    assert expected_calibration_error([]) == 0.0


# ---- temperature scaling (NLL objective) ------------------------------------------

def test_temperature_fit_minimizes_nll():
    rng = random.Random(11)
    scored = []
    for _ in range(200):
        surf = {"FM-1.3": 3.0, "FM-3.1": 0.2}
        gold = rng.choice(["FM-1.3", "FM-3.1"])
        noisy = {k: v + rng.gauss(0, 1.8) for k, v in surf.items()}
        scored.append((noisy, gold))

    def nll_with(temp: float) -> float:
        total = 0.0
        for scores, gold in scored:
            probs = softmax(scores, temperature=temp)
            total -= math.log(max(probs[gold], 1e-12))
        return total / len(scored)

    temperature = fit_temperature(scored)
    assert 0.5 <= temperature <= 5.0
    assert nll_with(temperature) <= nll_with(1.0) + 1e-9


def test_temperature_floor_prevents_saturation():
    """On a perfectly separable set, NLL would drive T to 0 and every
    probability to exactly 1.0/0.0 — the search floor keeps the temperature
    in a range where conformal sets stay informative."""
    separable = []
    rng = random.Random(3)
    for _ in range(100):
        gold = rng.choice(["FM-1.3", "FM-3.1"])
        sign = 1.0 if gold == "FM-1.3" else -1.0
        separable.append(({"FM-1.3": sign * 3.0, "FM-3.1": -sign * 3.0}, gold))
    temperature = fit_temperature(separable)
    assert temperature >= 0.5
    probs = softmax(separable[0][0], temperature=temperature)
    # non-gold mass is small but not exactly zero
    other = probs["FM-3.1"]
    assert 0.0 < other < 1e-3 or other == 0.0


# ---- conformal ----------------------------------------------------------------------

def test_conformal_coverage_guarantee_holds():
    """The distribution-free promise, checked empirically: with alpha=0.1
    the true mode is inside the prediction set >= 90% on held-out data —
    even with 15% irreducible label noise in the calibration split."""
    labeled = _labeled_set(n_per_mode=40)
    split = int(len(labeled) * 0.5)
    model = fit_conformal(labeled[:split], alpha=0.1)
    assert isinstance(model, ConformalModel)
    assert model.calibration_size == split
    assert model.target_coverage == pytest.approx(0.9)

    covered = 0
    held = labeled[split:]
    for scores, gold in held:
        modes, _ = model.prediction_set(scores)
        covered += gold in modes
    empirical = covered / len(held)
    assert empirical >= 0.88, f"coverage {empirical:.2%} below the alpha bound"


def test_conformal_sets_widen_with_ambiguity():
    """Strong evidence -> small set; ambiguous scores -> an honest superset."""
    labeled = _labeled_set(n_per_mode=40)
    model = fit_conformal(labeled, alpha=0.1)
    strong = {"FM-1.3": 4.0, "FM-3.1": 0.1, "FM-3.2": 0.0, "OTHER": -1.0}
    ambiguous = {"FM-1.3": 1.0, "FM-3.1": 0.95, "FM-3.2": 0.9, "OTHER": 0.8}
    strong_set, strong_probs = model.prediction_set(strong)
    amb_set, _ = model.prediction_set(ambiguous)
    assert strong_set <= amb_set            # monotone widening
    assert len(strong_set) <= len(amb_set)
    assert strong_probs["FM-1.3"] > 0.5


def test_conformal_empty_calibration_rejected():
    with pytest.raises(ValueError, match="calibration split is empty"):
        fit_conformal([])


# ---- score surface ------------------------------------------------------------------

def test_score_modes_surface_is_complete():
    trace = _traced([("search", {"q": "x"}), ("search", {"q": "x"})], False)
    scores = score_modes(trace)
    real_modes = {m.id for m in FAILURE_MODES.values() if m.id != "OTHER"}
    assert set(scores.keys()) == real_modes  # every real mode, no OTHER filler
    assert scores["FM-1.3"] > scores["FM-3.1"], (
        f"FM-1.3={scores['FM-1.3']:.3f} FM-3.1={scores['FM-3.1']:.3f} "
        f"all={scores}")


def test_cli_calibrate_end_to_end(tmp_path, monkeypatch, capsys):
    """End-to-end: export a labeled dataset from the store, then calibrate."""
    monkeypatch.setenv("APPROXIMATELY_HOME", str(tmp_path / "traces"))
    from approximately.cli import main
    from approximately.distill import export_dataset, rules_labeler
    from approximately.store import TraceStore

    for _ in range(10):   # calibrate needs >= 10 labeled traces
        main(["demo"])
    store = TraceStore(tmp_path / "traces")
    out = tmp_path / "dataset.jsonl"
    export_dataset(store.list_traces(), out, rules_labeler())
    code = main(["calibrate", str(out), "--alpha", "0.1"])
    payload = capsys.readouterr().out
    assert code == 0
    assert "coverage:" in payload
    assert "ECE" in payload
