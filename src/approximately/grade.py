"""Letter grades for agents and tools, from evidence on file.

A scorecard is a table; a grade is a verdict. :func:`grade_cards`
turns the cluster scorecards' per-subject rollups into letter grades
on three components — reliability (failure rate), discipline (error
share of calls), budget (breach stamps) — with a weighted composite.
Components with too little evidence grade ``n/a`` instead of
guessing, and an ungraded component never becomes an F.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# Composite weights: reliability first — an agent that fails its runs
# is not salvaged by tidy latency. Evidence floors before grading.
W_RELIABILITY = 0.5
W_DISCIPLINE = 0.25
W_BUDGET = 0.25
MIN_TRACES = 2

_GRADE_POINTS: Dict[str, float] = {"A": 4.0, "B": 3.0, "C": 2.0,
                                   "D": 1.0, "F": 0.0}


def _letter_rate(rate: float) -> str:
    if rate <= 0.05:
        return "A"
    if rate <= 0.15:
        return "B"
    if rate <= 0.30:
        return "C"
    if rate <= 0.50:
        return "D"
    return "F"


def _letter_errors(errors: int, calls: int) -> Optional[str]:
    if not calls:
        return None
    return _letter_rate(errors / calls)


def _letter_budget(breached: int) -> str:
    # a negative breach count is hand-edited nonsense: no evidence
    # of a breach is not a breach
    return "A" if breached <= 0 else "F"


def _composite(parts: List[Tuple[str, float]]) -> str:
    """Weighted grade points over ``(letter, weight)`` pairs; the
    weights renormalize when a component lacks evidence."""
    total_w = sum(w for _, w in parts)
    if not total_w:
        return "n/a"
    points = sum(_GRADE_POINTS[letter] * w
                 for letter, w in parts) / total_w
    if points >= 3.5:
        return "A"
    if points >= 3.0:
        return "B"
    if points >= 2.5:
        return "C"
    if points >= 2.0:
        return "D"
    return "F"


def grade_card(card: Dict[str, Any]) -> Dict[str, Any]:
    """Grade one scorecard row: reliability + discipline + budget.

    Fewer than MIN_TRACES touched -> every component ``n/a`` and the
    composite too: one flaky run is not a report card.
    """
    if card.get("traces", 0) < MIN_TRACES:
        return {
            "subject": card.get("agent") or card.get("tool"),
            "kind": "agent" if "agent" in card else "tool",
            "traces": card.get("traces", 0),
            "grade": "n/a",
            "reliability": None,
            "discipline": None,
            "budget": None,
        }
    reliability = _letter_rate(max(0.0,
                                   card.get("failure_rate", 0.0)))
    # agent cards count tool_calls; tool cards only have steps
    # (every step a tool row owns is a call it served)
    calls = max(0, card.get("tool_calls")
                or card.get("steps") or 0)
    discipline = _letter_errors(max(0, card.get("errors", 0)),
                                calls)
    budget = _letter_budget(card.get("breached_traces", 0))
    parts = [(reliability, W_RELIABILITY),
             (budget, W_BUDGET)]
    if discipline is not None:
        parts.append((discipline, W_DISCIPLINE))
    return {
        "subject": card.get("agent") or card.get("tool"),
        "kind": "agent" if "agent" in card else "tool",
        "traces": card.get("traces", 0),
        "grade": _composite(parts),
        "reliability": reliability,
        "discipline": discipline,
        "budget": budget,
    }


def below_floor(rows: List[Dict[str, Any]],
                floor: str) -> List[Dict[str, Any]]:
    """Graded rows strictly below the floor letter. ``n/a`` never
    fails — insufficient evidence is not a conviction; an unknown
    floor letter raises ValueError (refusal, not a typo-passed
    gate)."""
    if floor not in _GRADE_POINTS:
        raise ValueError(f"grade floor must be one of "
                         f"{sorted(_GRADE_POINTS)}, got {floor!r}")
    floor_points = _GRADE_POINTS[floor]
    return [r for r in rows
            if r["grade"] in _GRADE_POINTS
            and _GRADE_POINTS[r["grade"]] < floor_points]


def grade_cards(cards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Grade every row, best composite first (ungraded last)."""
    rows = [grade_card(c) for c in cards]
    rows.sort(key=lambda r: (-_GRADE_POINTS.get(r["grade"], -1.0),
                             r["subject"] or ""))
    return rows


def render_grades(rows: List[Dict[str, Any]],
                  kind: str = "agent") -> str:
    """Prose table: one row per subject, components spelled out."""
    if not rows:
        return f"nothing to grade: no {kind} evidence in the window"
    lines = [(f"{kind} grades (component letters: reliability / "
              "discipline / budget):")]
    for r in rows:
        def fmt(letter: Optional[str]) -> str:
            return letter if letter is not None else "n/a"

        lines.append(
            f"  {r['grade']:<3} {r['subject']!s:<24.24} "
            f"[{fmt(r['reliability'])}/{fmt(r['discipline'])}/"
            f"{fmt(r['budget'])}] over {r['traces']} traces")
    return "\n".join(lines)


def grade_store(store: Any, kind: str = "agent",
                subject: Optional[str] = None
                ) -> Tuple[List[Dict[str, Any]], str]:
    """The CLI/MCP door: scorecard -> grades for agents or tools,
    optionally narrowed to one subject (KeyError names it)."""
    from .cluster import agent_scorecard, tool_scorecard

    traces = store.list_traces()
    if kind == "tool":
        cards = tool_scorecard(traces)
        key = "tool"
    else:
        cards = agent_scorecard(traces)
        key = "agent"
    if subject is not None:
        cards = [c for c in cards if c.get(key) == subject]
        if not cards:
            raise KeyError(f"no {kind} {subject!r} in the window")
    return grade_cards(cards), kind


def _week_letters(window: List[Any], key: str, kind: str
                  ) -> Dict[str, str]:
    """Subject -> letter for one week's traces."""
    from .cluster import agent_scorecard, tool_scorecard

    cards = (tool_scorecard(window) if kind == "tool"
             else agent_scorecard(window))
    return {c[key]: g["grade"] for c, g in
            zip(cards, grade_cards(cards), strict=False)}


def _drift(cur: Optional[str], prev: Optional[str]) -> str:
    """Direction for one subject's letter pair; thin evidence is
    named, never graded."""
    if cur is None:
        return "gone"
    if prev is None:
        return "new"
    if "n/a" in (cur, prev):
        return "thin"
    d = _GRADE_POINTS[cur] - _GRADE_POINTS[prev]
    return "improved" if d > 0 else "slipped" if d < 0 else "flat"


def grade_trend(store: Any, kind: str = "agent",
                now: Optional[float] = None) -> Dict[str, Any]:
    """Week-over-week letter drift per subject: this week's grade
    vs last week's, from the trace's own clock (last 7 days vs the
    7 before). ``n/a`` on either side is thin evidence, not a
    verdict: the row reports both letters and no direction. A
    subject on file only last week reads ``gone``; only this week,
    ``new``."""
    import time

    from .trace import coerce_epoch

    now = now if now is not None else time.time()
    week = 7 * 86400.0
    traces = store.list_traces()
    cur = [t for t in traces
           if coerce_epoch(t.created_at) > now - week]
    prev = [t for t in traces
            if now - week >= coerce_epoch(t.created_at) > now - 2 * week]
    key = "tool" if kind == "tool" else "agent"

    cur_l = _week_letters(cur, key, kind)
    prev_l = _week_letters(prev, key, kind)
    rows = []
    for subject in sorted(set(cur_l) | set(prev_l)):
        a, b = cur_l.get(subject), prev_l.get(subject)
        rows.append({"subject": subject, "now": a, "prev": b,
                     "direction": _drift(a, b)})
    return {"kind": kind, "usable": bool(cur or prev),
            "this_week_traces": len(cur), "last_week_traces": len(prev),
            "subjects": rows}


def render_grade_trend(trend: Dict[str, Any]) -> str:
    """Prose: one line per subject, drift named; no two-week
    evidence says so."""
    if not trend["usable"]:
        return ("no two-week evidence yet: nothing on file in the "
                "last fortnight")
    lines = [(f"grade trend ({trend['kind']}s, this week vs last; "
             f"{trend['this_week_traces']} vs "
             f"{trend['last_week_traces']} traces):")]
    for r in trend["subjects"]:
        arrow = f"{r['prev']} -> {r['now']}"
        lines.append(f"  {r['subject']}: {arrow} ({r['direction']})")
    return "\n".join(lines)
