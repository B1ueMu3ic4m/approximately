"""Calibration and conformal prediction for attribution scores.

Raw fusion scores answer "which mode is most likely?" — but two questions
matter more in production:

1. **Is 0.8 confidence actually 80% right?** (calibration). Detectors'
   hand-assigned confidences are rarely calibrated; temperature scaling on
   the score surface fixes the miscalibration, measured by ECE (expected
   calibration error).

2. **Which modes are plausible at all?** (conformal attribution). A point
   answer hides uncertainty. Split-conformal prediction turns a calibration
   set into a *prediction set* of modes carrying a distribution-free
   guarantee: the true mode is in the set with probability >= 1 - alpha,
   no matter how miscalibrated the underlying scores are (only
   exchangeability is assumed).

This module implements both against labeled trace sets, plus the
score-surface plumbing they need.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Sequence, Tuple

from .attributor import score_modes
from .trace import Trace  # noqa: F401 - re-exported type used by callers

# ---------------------------------------------------------------- softmax


def softmax(scores: Dict[str, float],
            temperature: float = 1.0) -> Dict[str, float]:
    """Temperature-scaled softmax over a score surface."""
    if temperature <= 0:
        raise ValueError("temperature must be positive")
    top = max(scores.values())
    exp = {k: math.exp((v - top) / temperature) for k, v in scores.items()}
    total = sum(exp.values())
    return {k: v / total for k, v in exp.items()}


# ---------------------------------------------------------------- ECE


def expected_calibration_error(pairs: Sequence[Tuple[float, bool]],
                               bins: int = 10) -> float:
    """ECE over (predicted_probability, correct) pairs, equal-width bins.

    ECE = sum over bins of (bin share) * |mean confidence - accuracy|.
    0.0 = perfectly calibrated; lower is better.
    """
    if not pairs:
        return 0.0
    bucket: List[List[Tuple[float, bool]]] = [[] for _ in range(bins)]
    for prob, correct in pairs:
        idx = min(bins - 1, int(prob * bins))
        bucket[idx].append((prob, correct))
    ece = 0.0
    for samples in bucket:
        if not samples:
            continue
        mean_conf = sum(p for p, _ in samples) / len(samples)
        accuracy = sum(1 for _, c in samples if c) / len(samples)
        ece += (len(samples) / len(pairs)) * abs(mean_conf - accuracy)
    return ece


def fit_temperature(scored: Sequence[Tuple[Dict[str, float], str]],
                    lo: float = 0.5, hi: float = 5.0,
                    iterations: int = 40) -> float:
    """Golden-section search for the temperature minimizing NLL.

    The objective is negative log-likelihood of the true mode (Guo et al.
    2017's temperature-scaling criterion) — NOT ECE: on a separable
    calibration set, ECE collapses to the degenerate temperature 0 where
    probabilities saturate and every conformal set comes back empty. NLL is
    a proper scoring rule; ECE stays available as a *reporting* metric.
    """
    def nll_at(t: float) -> float:
        total = 0.0
        for scores, gold in scored:
            probs = softmax(scores, temperature=t)
            total -= math.log(max(probs.get(gold, 0.0), 1e-12))
        return total / max(1, len(scored))

    inv_phi = (math.sqrt(5) - 1) / 2
    a, b = lo, hi
    c = b - inv_phi * (b - a)
    d = a + inv_phi * (b - a)
    for _ in range(iterations):
        if nll_at(c) < nll_at(d):
            b = d
        else:
            a = c
        c = b - inv_phi * (b - a)
        d = a + inv_phi * (b - a)
    return round((a + b) / 2, 4)


# ---------------------------------------------------------------- conformal


@dataclass
class ConformalModel:
    """Split-conformal attribution with a distribution-free coverage bound.

    Fit on a labeled calibration split; ``prediction_set`` then returns a
    set of modes containing the true mode with probability >= 1 - alpha
    (exchangeability assumed — that is the only assumption).
    """

    alpha: float
    threshold: float
    temperature: float
    calibration_size: int
    scores_of: Callable = field(default=score_modes, repr=False)

    @property
    def target_coverage(self) -> float:
        return 1 - self.alpha

    def prediction_set(self, trace_or_scores) -> Tuple[set, Dict[str, float]]:
        """Modes plausibly responsible, with their calibrated probabilities.

        Accepts a Trace (scores computed via ``scores_of``) or a raw score
        surface dict.
        """
        scores = (trace_or_scores if isinstance(trace_or_scores, dict)
                  else self.scores_of(trace_or_scores))
        probs = softmax(scores, temperature=self.temperature)
        return ({m for m, p in probs.items() if 1 - p <= self.threshold},
                probs)


def fit_conformal(scored: Sequence[Tuple[Dict[str, float], str]],
                  alpha: float = 0.1,
                  temperature: float | None = None) -> ConformalModel:
    """Split-conformal fit from a labeled calibration split.

    Nonconformity score of a labeled example: 1 - softmax-probability of
    the true mode. The conformal threshold is the ceil((n+1)(1-alpha))-th
    smallest such score (the standard finite-sample quantile).
    """
    if not scored:
        raise ValueError("calibration split is empty")
    t = temperature if temperature is not None else fit_temperature(scored)

    def nonconformity(scores: Dict[str, float], gold: str) -> float:
        probs = softmax(scores, temperature=t)
        return 1 - probs.get(gold, 0.0)

    nc = sorted(nonconformity(scores, gold) for scores, gold in scored)
    n = len(nc)
    rank = max(0, math.ceil((n + 1) * (1 - alpha)) - 1)
    threshold = nc[min(rank, n - 1)]
    return ConformalModel(alpha=alpha, threshold=threshold, temperature=t,
                          calibration_size=n)
