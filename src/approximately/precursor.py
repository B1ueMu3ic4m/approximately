"""Failure-precursor prediction: an n-gram early-warning model over actions.

Mined from your own store: which *prefixes of actions* historically precede
failure? The model is a smoothed conditional over action n-grams
(n = 1..max_n):

    P(fail | ngram) = (failures(ngram) + alpha) / (occurrences(ngram) + 2*alpha)

with add-alpha (Laplace) smoothing, so unseen prefixes score exactly 0.5
(no evidence) instead of dividing by zero. Per-n log-odds are combined with
support weighting — an n-gram seen 40 times is worth more than one seen
once:

    log-odds(prefix) = sum over n of support(n) * logit(P(fail | ngram_n))
    probability      = sigmoid(log-odds / total support)

The result is a probability in (0, 1) computed from your own history —
"runs that look like *this* have historically failed Z% of the time".
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Tuple

from .align import normalize_step
from .trace import Trace

MAX_N = 3
ALPHA = 1.0  # Laplace smoothing


def _prefix_tokens(trace: Trace) -> List[str]:
    # structure tokens (kind:tool {arg-keys}) — the SHAPE of an action
    # generalizes across runs; raw values would never repeat exactly
    return [structure for _identity, structure in
            (normalize_step(s) for s in trace.steps if s.kind == "tool_call")]


def _ngrams(tokens: List[str], n: int) -> List[Tuple[str, ...]]:
    return [tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)]


@dataclass
class PrecursorModel:
    """Failure-conditional n-gram statistics over a store of traces."""

    occurrences: Dict[int, Dict[Tuple[str, ...], int]] = field(default_factory=dict)
    failures: Dict[int, Dict[Tuple[str, ...], int]] = field(default_factory=dict)
    traces_mined: int = 0
    failed_traces_mined: int = 0

    # -- training ------------------------------------------------------------
    def observe(self, trace: Trace) -> None:
        failed = trace.success is False
        toks = _prefix_tokens(trace)
        for n in range(1, MAX_N + 1):
            occ = self.occurrences.setdefault(n, {})
            fail = self.failures.setdefault(n, {})
            for gram in _ngrams(toks, n):
                occ[gram] = occ.get(gram, 0) + 1
                if failed:
                    fail[gram] = fail.get(gram, 0) + 1
        self.traces_mined += 1
        self.failed_traces_mined += failed

    # -- inference -----------------------------------------------------------
    def _conditional(self, gram: Tuple[str, ...], n: int) -> Tuple[float, int]:
        occ = self.occurrences.get(n, {}).get(gram, 0)
        fail = self.failures.get(n, {}).get(gram, 0)
        p = (fail + ALPHA) / (occ + 2 * ALPHA)
        return p, occ

    def probability(self, trace: Trace) -> "PrecursorScore":
        toks = _prefix_tokens(trace)
        logodds_sum = 0.0
        support_sum = 0
        contributors: List[dict] = []
        for n in range(1, MAX_N + 1):
            grams = _ngrams(toks, n)
            if not grams:
                continue
            # the most-observed n-gram of this length in the prefix is the
            # signal at that order (highest support wins)
            best = max((_conditional_pair(gram, self) for gram in grams),
                       key=lambda pair: pair[1])
            p, occ = best
            if occ == 0:
                continue  # unobserved at this order: no evidence
            support = min(occ, 20)  # cap: one hot pattern != infinite weight
            weight = support * n  # longer, well-supported grams count more
            logodds_sum += weight * math.log(p / (1 - p))
            support_sum += weight
            contributors.append({"ngram": list(grams[-1]) if grams else [],
                                 "n": n, "p_fail": round(p, 3),
                                 "support": occ})
        if support_sum == 0:
            return PrecursorScore(probability=0.5, contributors=[],
                                  mined_traces=self.traces_mined,
                                  detail="no observed precursors: prior 0.5")
        probability = 1 / (1 + math.exp(-logodds_sum / support_sum))
        return PrecursorScore(probability=probability,
                              contributors=contributors,
                              mined_traces=self.traces_mined)


def _conditional_pair(gram: Tuple[str, ...],
                      model: "PrecursorModel") -> Tuple[float, int]:
    n = len(gram)
    return model._conditional(gram, n)


@dataclass
class PrecursorScore:
    probability: float
    contributors: List[dict] = field(default_factory=list)
    mined_traces: int = 0
    detail: str = ""

    @property
    def verdict(self) -> str:
        if self.probability >= 0.7:
            return "HIGH RISK"
        if self.probability >= 0.45:
            return "elevated"
        return "normal"

    def summary(self) -> str:
        lines = [(f"failure probability {self.probability:.0%} "
                  f"[{self.verdict}] (mined from "
                  f"{self.mined_traces} traces)")]
        lines.extend(
            f"  {c['n']}-gram support {c['support']}: "
            f"historical failure rate {c['p_fail']:.0%}"
            for c in self.contributors)
        if self.detail:
            lines.append(f"  {self.detail}")
        return "\n".join(lines)


def mine(traces: Iterable[Trace]) -> PrecursorModel:
    model = PrecursorModel()
    for trace in traces:
        model.observe(trace)
    return model
