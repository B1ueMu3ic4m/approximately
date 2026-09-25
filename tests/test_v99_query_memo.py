"""v99: per-select field memoization — heavy fields pay once per trace.

Before: an expression mentioning ``mode`` N times ran the full
detector suite N times per trace (select over a store = N x runs).
Now ``select()`` passes a memo so every (trace, field) pair computes
at most once; ``parse()`` without a memo keeps the old eager behavior
(single-use predicates, e.g. inside attribution, see no overhead and
no shared state).
"""

from __future__ import annotations

from approximately.query import parse, select
from approximately.recorder import Recorder


def _trace(i, ok, agent=None):
    rec = Recorder(f"task {i}", save=False)
    rec.trace.id = f"q-{i}"
    rec.tool("search", {"q": i}, result=None if not ok else "hit",
             error=None if ok else "timeout", agent=agent)
    rec.respond("done", success=ok, agent=agent)
    return rec.trace


def _traces():
    return [_trace(0, False), _trace(1, True), _trace(2, False, "a")]


def test_memoized_mode_runs_detector_once_per_trace():
    calls = {"n": 0}
    real_run = None

    import approximately.detectors as dets

    def counting_run(trace):
        calls["n"] += 1
        return real_run(trace)

    real_run = dets.run_rules
    traces = _traces()
    try:
        dets.run_rules = counting_run
        found = select(traces, "mode == FM-2.1 or mode != FM-2.1")
    finally:
        dets.run_rules = real_run
    assert len(found) == 3
    # 3 traces x 2 mentions = 6 eager evaluations; memoized = 3
    assert calls["n"] == 3, calls


def test_memo_across_evaluations_not_shared_between_selects():
    """A fresh select() gets a fresh memo — no stale cross-call state."""
    traces = _traces()
    a = select(traces, "mode != FM-9.9")
    b = select(traces, "mode != FM-9.9")
    assert len(a) == len(b) == 3


def test_parse_without_memo_keeps_eager_behavior():
    p = parse("tokens >= 0 and tokens <= 100")
    assert len([t for t in _traces() if p(t)]) == 3


def test_memoized_tokens_field_consistent():
    traces = _traces()
    found = select(traces, "tokens >= 0 and tokens <= 100")
    assert len(found) == 3
