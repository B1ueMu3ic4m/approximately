"""v178: `max_latency` joins the query DSL.

`duration` sums every step; what night ops actually ask is "which
runs had a step slower than N" — the fleet anomaly story in query
form. `max_latency > 5000` selects traces whose slowest *timed tool
call* crossed the line (untimed/zero steps never count).
"""

import pytest

from approximately.query import QueryError, select
from approximately.recorder import Recorder


def _trace(task, latencies):
    rec = Recorder(task, save=False)
    for i, _ in enumerate(latencies):
        rec.tool("deploy", {"i": i}, result="ok")
    rec.respond("done", success=True)
    for step, ms in zip(rec.trace.steps, latencies, strict=False):
        step.latency_ms = ms
    return rec.trace


def test_max_latency_selects_the_slow_run():
    traces = [_trace("fast", [100, 120, 90]),
              _trace("slow", [100, 120, 9000])]
    hits = select(traces, "max_latency > 5000")
    assert [t.task for t in hits] == ["slow"]


def test_max_latency_ignores_untimed_steps():
    traces = [_trace("no timing", [0, 0, 0])]
    assert select(traces, "max_latency > 0") == []
    # and a floor of exactly the max still excludes it (strict >)
    hits = select(traces, "max_latency > 0.5")
    assert hits == []


def test_unknown_field_still_errors():
    with pytest.raises(QueryError, match="max_latenc"):
        select([], "max_latenc > 5")
