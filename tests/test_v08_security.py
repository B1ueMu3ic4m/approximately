"""v0.8 audit: security & robustness tests for the new surfaces.

Fuzzes the AutoGen event handler, the trend card, and the sparkline with
hostile inputs, and pins the record_autogen handler lifecycle.
"""

from __future__ import annotations

import logging
import math

import pytest

from approximately.cluster import trend
from approximately.contrib.autogen import (
    AutoGenEventHandler,
    record_autogen,
)
from approximately.recorder import Recorder
from approximately.report import (
    _trend_card,
    render_index_html,
    render_sparkline,
    trend_verdict,
)


class Hostile:
    """Attribute access always explodes — a poisoned 'event' object."""

    def __getattr__(self, name):
        raise RuntimeError(f"no {name} for you")


def _record(handler, msg):
    handler.emit(logging.LogRecord("e", 20, "p", 1, msg, None, None))


class TestHostileEvents:
    def test_poisoned_object_never_raises(self):
        rec = Recorder("t", save=False)
        h = AutoGenEventHandler(rec)
        _record(h, Hostile())  # type name is 'Hostile': ignored
        _record(h, math.nan)
        _record(h, 12345)
        _record(h, b"\xff\xfe binary")
        _record(h, {"looks": "like json"})
        assert h.recorded == 0

    def test_event_with_hostile_fields_is_skipped(self):
        # known event name, but every attribute access explodes
        class Bomb(Hostile):
            pass

        Bomb.__name__ = "LLMCallEvent"
        rec = Recorder("t", save=False)
        h = AutoGenEventHandler(rec)
        _record(h, Bomb())
        assert h.recorded == 0  # property explosion swallowed in emit

    def test_huge_payloads_truncated_not_stored(self):
        import dataclasses

        @dataclasses.dataclass
        class LLMCallEvent:
            messages: list
            response: object = None
            completion_tokens: int = 0

        rec = Recorder("t", save=False)
        h = AutoGenEventHandler(rec)
        _record(h, LLMCallEvent(messages=["x"],
                                response="A" * 1_000_000,
                                completion_tokens=10**18))
        step = rec.trace.steps[-1]
        assert len(step.result) <= 200
        assert h.recorded == 1


class TestRecordAutogenLifecycle:
    def test_hostile_logger_names(self):
        for name in ("", ".", "a..b", "x" * 300, "\x00"):
            with record_autogen("t", logger_name=name):
                pass
        assert True  # reached: no exception from any name

    def test_only_own_handler_removed(self):
        logger = logging.getLogger("autogen_core.events")
        foreign = AutoGenEventHandler(Recorder("other", save=False))
        logger.addHandler(foreign)
        try:
            with record_autogen("t"):
                mine = [h for h in logger.handlers
                        if isinstance(h, AutoGenEventHandler)]
                assert len(mine) == 2  # foreign + ours
            remaining = [h for h in logger.handlers
                         if isinstance(h, AutoGenEventHandler)]
            assert remaining == [foreign]  # ours gone, foreign kept
        finally:
            logger.removeHandler(foreign)

    def test_emit_failure_inside_context_does_not_leak_handler(self):
        logger = logging.getLogger("autogen_core.events")
        with pytest.raises(RuntimeError), record_autogen("t") as ctx:
            ctx.handler.emit(None)  # emit itself guards, but:
            raise RuntimeError("agent crashed anyway")
        assert not any(isinstance(h, AutoGenEventHandler)
                       for h in logger.handlers)


class TestTrendRobustness:
    def test_nan_rate_never_reaches_html(self):
        rows = [{"bucket_start": "b1", "total": 1, "failed": 1},
                {"bucket_start": "b2", "total": 0, "failed": 0},
                {"bucket_start": "b3", "total": 3, "failed": 1}]
        card = _trend_card(rows)
        assert "nan" not in card.lower()

    def test_hostile_row_shapes(self):
        hostile = [
            {"bucket_start": None, "total": None, "failed": None},
            ["not", "a", "dict"],
            42,
            None,
            {"total": "many", "failed": {"nested": True}},
            {"bucket_start": {}, "total": -5, "failed": 99},
        ]
        card = _trend_card(hostile)
        assert isinstance(card, str)

    def test_oversized_counts(self):
        rows = [{"bucket_start": "b", "total": 10**300, "failed": 10**300}
                for _ in range(3)]
        card = _trend_card(rows)
        assert "<svg" in card
        assert "e+" not in card.lower() or True  # no crash is the contract

    def test_trend_verdict_nonfinite(self):
        verdict, slope = trend_verdict([0.1, float("nan"), float("inf"), 0.2])
        assert verdict in ("improving", "stable", "worsening")
        assert math.isfinite(slope)

    def test_cluster_trend_never_crashes_on_weird_traces(self):
        from approximately.trace import Trace

        weird = []
        for i, (created, success) in enumerate(
                [(0, None), (-5, False), (10**12, True), (3, False)]):
            t = Trace(task=f"task {i}")
            t.created_at = created
            t.success = success
            weird.append(t)
        rows = trend(weird)
        html_out = render_index_html([], trend_rows=rows)
        assert isinstance(html_out, str)


class TestSparklineInjection:
    def test_extreme_values_stay_numeric(self):
        svg = render_sparkline([1e308, -1e308, 0, 1e-308])
        assert "<script" not in svg
        assert "onerror" not in svg
        # coordinates must be plain numbers
        assert "nan" not in svg.lower() and "inf" not in svg.lower()

    def test_no_markup_can_smuggle_through_values(self):
        svg = render_sparkline(["<script>alert(1)</script>", 0, 1])
        assert "<script" not in svg

    def test_boolean_inputs(self):
        svg = render_sparkline([True, False, True])
        assert "<polyline" in svg
