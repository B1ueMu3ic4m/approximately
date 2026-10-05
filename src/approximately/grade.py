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
