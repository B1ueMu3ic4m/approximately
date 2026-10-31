"""v360: the context doors meet degenerate traces.

The budget doors (composition, forecast, optimize_budget) saw a
1 MB single-step trace and an empty one in tonight's audit: no
crash, shapes hold. Pinned so the doors stay honest about
degenerate input.
"""

import tempfile

from approximately.context import (composition, estimate_tokens,
                                   forecast, optimize_budget)
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store():
    return TraceStore(tempfile.mkdtemp())


def test_empty_trace_composes_without_drama():
    store = _store()
    rec = Recorder("empty", store=store, save=False)
    rec.respond("done", success=True)
    c = composition(rec.trace)
    assert "total_tokens" in c and "parts" in c
    assert c["total_tokens"] >= 0


def test_one_megabyte_step_forecasts_within_budget_math():
    store = _store()
    rec = Recorder("huge", store=store, save=False)
    rec.tool("x", {}, result="y" * 1_000_000)
    rec.respond("done", success=True)
    f = forecast(rec.trace, budget=100)
    assert f is not None
    o = optimize_budget(rec.trace, min_recall=0.5)
    assert o is not None


def test_estimate_tokens_floor_is_one():
    assert estimate_tokens("hello world") > 0
    assert estimate_tokens("") == 1, \
        "the floor is deliberate: a 0-token item would vanish \
from the budget math"
