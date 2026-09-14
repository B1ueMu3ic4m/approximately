"""v0.8: report trend analytics — sparkline, Theil-Sen slope, verdict card."""

from __future__ import annotations

from typing import ClassVar

from approximately.report import (
    _trend_card,
    render_index_html,
    render_sparkline,
    theil_sen_slope,
    trend_verdict,
)


class TestSparkline:
    def test_svg_structure(self):
        svg = render_sparkline([1, 2, 3, 2])
        assert svg.startswith("<svg")
        assert "<polyline" in svg and "points=" in svg
        assert "</svg>" in svg

    def test_single_value_flattened(self):
        svg = render_sparkline([7])
        assert svg.count("<polyline") == 1

    def test_constant_series_midline(self):
        svg = render_sparkline([5, 5, 5, 5])
        assert ",20.0" in svg  # all points on the vertical midline

    def test_empty_becomes_flat(self):
        assert "<polyline" in render_sparkline([])

    def test_nonfinite_and_bad_inputs_safe(self):
        svg = render_sparkline([float("nan"), float("inf"), None, "x", 3])
        assert "nan" not in svg.lower()
        assert "<polyline" in svg

    def test_no_script_injection_possible(self):
        svg = render_sparkline([1e308, -1e308, 0])  # extremes stay numeric
        assert "<script" not in svg


class TestTheilSen:
    def test_perfect_uptrend(self):
        assert theil_sen_slope([0, 1, 2, 3]) == 1.0

    def test_outlier_resisted(self):
        # one wild bucket must not drag the slope like OLS would
        clean = [0.1, 0.12, 0.11, 0.13, 0.12]
        spiked = [0.1, 0.12, 0.95, 0.13, 0.12]
        assert abs(theil_sen_slope(spiked) - theil_sen_slope(clean)) < 0.15

    def test_short_series_zero(self):
        assert theil_sen_slope([1]) == 0.0
        assert theil_sen_slope([]) == 0.0

    def test_nonfinite_treated_as_zero(self):
        assert theil_sen_slope([float("nan"), 1, 2]) >= 0


class TestVerdict:
    def test_worsening(self):
        verdict, slope = trend_verdict([0.1, 0.2, 0.4, 0.7])
        assert verdict == "worsening" and slope > 0

    def test_improving(self):
        verdict, _ = trend_verdict([0.7, 0.4, 0.2, 0.1])
        assert verdict == "improving"

    def test_stable_flat(self):
        verdict, slope = trend_verdict([0.3, 0.3, 0.3, 0.3])
        assert verdict == "stable" and slope == 0.0

    def test_noise_on_high_rate_is_stable(self):
        # 2-point jitter on a 60% rate is noise, not a trend
        verdict, _ = trend_verdict([0.60, 0.62, 0.59, 0.61])
        assert verdict == "stable"


class TestTrendCard:
    ROWS: ClassVar[list] = [
        {"bucket_start": "2026-08-30", "total": 10, "failed": 1},
        {"bucket_start": "2026-09-06", "total": 10, "failed": 3},
        {"bucket_start": "2026-09-13", "total": 10, "failed": 6},
    ]

    def test_card_renders_with_verdict(self):
        card = _trend_card(self.ROWS)
        assert "Failure-rate trend" in card
        assert "<svg" in card
        assert "Theil-Sen" in card

    def test_escapes_bucket_strings(self):
        rows = [{"bucket_start": '"><script>alert(1)</script>',
                 "total": 1, "failed": 0}]
        assert "<script>" not in _trend_card(rows)

    def test_bad_rows_yield_empty(self):
        assert _trend_card([]) == ""
        assert _trend_card([{"total": 0, "failed": 0}]) == ""
        assert _trend_card("not a list of dicts") == ""


class TestIndexIntegration:
    def test_index_without_trend_backward_compatible(self):
        html_out = render_index_html([])
        assert "Failure-rate trend" not in html_out
        assert "postmortem index" in html_out

    def test_index_with_trend(self):
        html_out = render_index_html([], trend_rows=TestTrendCard.ROWS)
        assert "Failure-rate trend" in html_out
        assert "no traces yet" in html_out
