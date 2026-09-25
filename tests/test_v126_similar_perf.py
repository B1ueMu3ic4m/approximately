"""v126: rank_similar pruning — same ranking as brute force, faster.

The optimizer hoists target-token normalization and skips the
quadratic DP for candidates whose length-ratio upper bound sits
strictly below the current Nth-best score. This pins the exact
ranking equality (ids and scores) against a brute-force reference,
plus a store-shape sanity check.
"""

from approximately.align import rank_similar
from approximately.recorder import Recorder


def _trace(i, tools):
    rec = Recorder(f"t {i}", save=False)
    rec.trace.id = f"p-{i}"
    for j, tool in enumerate(tools):
        rec.tool(tool, {"i": j}, result="ok")
    rec.respond("done", success=bool(i % 2))
    return rec.trace


def _brute(target, traces, top):
    from approximately.align import MATCH_SCORE, align_score, tokens

    tgt = tokens(target)
    scored = []
    for c in traces:
        if c.id == target.id:
            continue
        tc = tokens(c)
        if not tgt or not tc:
            score = 0.0
        else:
            score = max(0.0, min(
                1.0, align_score(tgt, tc)
                / (MATCH_SCORE * max(len(tgt), len(tc)))))
        scored.append((c, score))
    scored.sort(key=lambda pair: -pair[1])
    return scored[:top]


def test_ranking_equals_brute_force():
    shapes = [["search", "book"], ["search", "book", "pay"],
              ["search"], ["deploy", "smoke"],
              ["search", "book"], ["cancel"], ["search", "cancel"],
              ["deploy"], ["search", "book", "pay", "confirm"]]
    traces = [_trace(i, shapes[i % len(shapes)]) for i in range(30)]
    target = _trace(99, ["search", "book"])
    got = rank_similar(target, traces, top=5)
    expected = _brute(target, traces, 5)
    assert [c.id for c, _ in got] == [c.id for c, _ in expected]
    assert [s for _, s in got] == [round(s, 10) for _, s in expected]


def test_ranking_top_one_and_all():
    shapes = [["search"], ["search", "book"], ["deploy"]]
    traces = [_trace(i, shapes[i % 3]) for i in range(9)]
    target = _trace(50, ["search", "book"])
    one = rank_similar(target, traces, top=1)
    assert len(one) == 1
    everything = rank_similar(target, traces, top=99)
    assert len(everything) == 9  # includes zero-score candidates


def test_tool_prometheus_grouping():
    from approximately.cluster import tool_scorecard
    from approximately.metrics import render_tool_prometheus

    shapes = [["search", "book"], ["search", "book", "pay"],
              ["deploy"]]
    traces = [_trace(i, shapes[i % 3]) for i in range(6)]
    rows = tool_scorecard(traces)
    text = render_tool_prometheus(rows)
    assert "approximately_tool_failure_rate{tool=" in text
    assert "search" in text and "deploy" in text
