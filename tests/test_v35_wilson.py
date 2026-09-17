"""v0.35: Wilson score intervals on benchmark precision/recall.

Point estimates on small n lie. The 95% Wilson interval (Wilson
1927) stays inside [0, 1] and does not degenerate at 0 or n successes
the way the normal approximation does; every per-mode P and R now
carries one.
"""

from __future__ import annotations

import pytest

from approximately.cli import cmd_benchmark
from approximately.distill import wilson_interval
from approximately.recorder import Recorder


class TestWilsonInterval:
    def test_known_values(self):
        # Direct formula check: p = 81/263, z = 1.96
        # center (0.308+3.8416/526)/1.0146 = 0.3108,
        # spread 1.96*sqrt(0.308*0.692/263 + 3.8416/4n^2)/1.0146 = 0.0554
        lo, hi = wilson_interval(81, 263)
        assert abs(lo - 0.2554) < 0.002
        assert abs(hi - 0.3662) < 0.002

    def test_single_success_interval(self):
        # standard reference: 1/1 -> (0.2065, 1.0)
        lo, hi = wilson_interval(1, 1)
        assert abs(lo - 0.2065) < 0.002
        assert hi == 1.0

    def test_degenerate_zero_and_full_successes(self):
        assert wilson_interval(0, 10)[0] == 0.0
        assert wilson_interval(0, 10)[1] < 0.31  # not zero-width
        assert wilson_interval(10, 10)[1] == 1.0
        assert wilson_interval(10, 10)[0] > 0.69

    def test_empty_sample(self):
        assert wilson_interval(0, 0) == (0.0, 0.0)

    def test_always_inside_unit_interval(self):
        import random

        rng = random.Random(7)
        for _ in range(200):
            n = rng.randint(1, 500)
            s = rng.randint(0, n)
            lo, hi = wilson_interval(s, n)
            assert 0.0 <= lo <= hi <= 1.0

    def test_narrower_with_more_data(self):
        narrow = wilson_interval(50, 100)
        wide = wilson_interval(5, 10)
        assert (narrow[1] - narrow[0]) < (wide[1] - wide[0])


class TestPrfIntegration:
    def _trace(self, ok: bool):
        rec = Recorder("task", save=False)
        rec.trace.success = ok
        return rec.trace

    def test_prf_carries_intervals(self):
        from approximately.distill import _prf

        m = _prf(7, 6, 4)
        p_lo, p_hi = m["precision_ci"]
        assert 0.0 <= p_lo <= m["precision"] <= p_hi <= 1.0
        r_lo, r_hi = m["recall_ci"]
        assert 0.0 <= r_lo <= m["recall"] <= r_hi <= 1.0

    def test_zero_counts_give_zero_interval(self):
        from approximately.distill import _prf

        m = _prf(0, 0, 5)
        assert m["precision_ci"] == (0.0, 0.0)


class TestBenchmark:
    def test_multi_label_prints_intervals(self, capsys):
        from pathlib import Path

        dataset = Path("docs/mast-bench-multi.jsonl")
        if not dataset.exists():
            pytest.skip("benchmark corpus not present")
        args = type("A", (), {"dataset": str(dataset), "html": None,
                              "format": "jsonl", "multi_label": True})()
        assert cmd_benchmark(args) == 0
        out = capsys.readouterr().out
        assert "[" in out and "]" in out  # interval brackets present
