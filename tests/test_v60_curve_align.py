"""v0.60 — curve SVG helpers and align similarity/ranking, direct tests."""

from __future__ import annotations

from approximately.align import rank_similar, similarity, tokens
from approximately.curve import BudgetCurve, CurvePoint, render_curve_html
from approximately.recorder import Recorder


def _trace(tid, tools, ok=True):
    rec = Recorder("curve/align fixture", save=False)
    rec.trace.id = tid
    for t in tools:
        rec.tool(t, {"path": f"{t}.py"}, result=f"{t} ok")
    rec.respond("done" if ok else "failed", success=ok)
    return rec.trace


# -- curve SVG geometry ------------------------------------------------------

def _curve(*budget_recall):
    pts = [CurvePoint(budget=b, tokens_used=b, recall=r)
           for b, r in budget_recall]
    return BudgetCurve(trace_id="c", full_tokens=100, points=pts)


def test_to_svg_points_maps_budget_recall_to_viewport():
    curve = _curve((0, 0.0), (100, 1.0))
    pts = curve.to_svg_points(width=200, height=100, pad=10).split()
    assert pts[0] == "10.0,90.0"  # budget 0, recall 0 -> bottom-left
    assert pts[1] == "190.0,10.0"  # budget max, recall 1 -> top-right


def test_to_svg_points_empty_curve_defaults_max_budget():
    curve = BudgetCurve(trace_id="c", full_tokens=0)
    assert curve.to_svg_points(width=100, height=100, pad=5) == ""


def test_render_curve_html_includes_polyline_and_dots():
    html = render_curve_html(_curve((40, 0.5), (80, 1.0)))
    assert "<polyline" in html and "points=" in html
    assert "circle" in html or "text" in html  # labeled dots


def test_svg_line_empty_points_renders_nothing():
    from approximately.curve import _svg_line

    assert _svg_line([], 100, 100, 5, "#000") == ""


def test_svg_line_single_point_uses_unit_span():
    from approximately.curve import _svg_line

    line = _svg_line([(0.0, 0.5)], 100, 100, 5, "#123456")
    assert 'stroke="#123456"' in line and "points=" in line


# -- align similarity and ranking --------------------------------------------

def test_similarity_identical_shapes_score_high():
    a = _trace("a", ["fetch", "parse", "store"])
    b = _trace("b", ["fetch", "parse", "store"])
    assert similarity(a, b) == 1.0


def test_similarity_empty_traces_score_zero():
    a = _trace("a", [])
    b = _trace("b", ["fetch"])
    assert similarity(a, b) == 0.0


def test_tokens_only_covers_tool_calls():
    # documented contract: identity/structure pairs for every
    # tool-call step - plan/response steps carry no alignment tokens
    rec = Recorder("think first", save=False)
    rec.tool("fetch", {"path": "a.py"}, result="ok")
    rec.respond("plan it out", success=True)
    toks = tokens(rec.trace)
    assert len(toks) == 1
    assert toks[0][0].startswith("tool_call:fetch")
    assert "path" in toks[0][1]


def test_rank_similar_orders_and_excludes_self():
    target = _trace("t", ["fetch", "parse", "store"])
    same = _trace("s1", ["fetch", "parse", "store"])
    other = _trace("s2", ["build", "test", "deploy"])
    ranked = rank_similar(target, [target, other, same])
    assert ranked[0][0].id == "s1"
    assert ranked[0][1] >= ranked[-1][1]
    assert all(t.id != "t" for t, _ in ranked)


def test_tokens_non_tool_step_uses_thought_branch():
    # non-tool steps carry a thought/result-derived state token
    rec = Recorder("think first", save=False)
    rec.respond("plan it out", success=True)
    toks = tokens(rec.trace)  # empty: contract excludes non-tool steps
    assert toks == []
    # the branch itself is reachable via normalize_step on a plan step
    from approximately.align import normalize_step
    from approximately.trace import PLAN, Step

    head, state = normalize_step(Step(kind=PLAN, thought="Plan the thing"))
    assert head == f"{PLAN}:-"
    assert "plan the thing" in state


def test_rank_similar_respects_top():
    target = _trace("t", ["fetch"])
    others = [_trace(f"o{i}", ["fetch"]) for i in range(5)]
    assert len(rank_similar(target, others, top=2)) == 2
