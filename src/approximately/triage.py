"""The triage queue: which failed runs deserve the morning first.

Every failed trace is not equally worth a postmortem. :func:`triage`
ranks a store's failures by a transparent, explainable score —
novelty of the failure mode dominates, burn and blast radius and
recency nudge the order — so the queue reads top-down instead of
file-ctime order. Every component is reported per row: the number is
never a verdict without its reasons.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .attributor import attribute
from .trace import Trace, coerce_epoch

# Score weights: novelty first — a brand-new failure mode outranks
# the tenth recurrence of a known one. The rest are tie-breakers
# with documented ratios so the ranking can be argued with.
W_NOVELTY = 2.0
W_COST = 1.0
W_BLAST = 1.0
W_RECENCY = 0.5


@dataclass
class TriageRow:
    """One failed run's place in the morning queue."""

    trace_id: str
    task: str
    mode: str
    score: float
    novelty: float
    cost_norm: float
    blast_norm: float
    recency_norm: float
    tokens: int
    agents: List[str] = field(default_factory=list)
    annotated: bool = False

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "task": self.task,
            "mode": self.mode,
            "score": round(self.score, 3),
            "parts": {
                "novelty": round(self.novelty, 3),
                "cost": round(self.cost_norm, 3),
                "blast": round(self.blast_norm, 3),
                "recency": round(self.recency_norm, 3),
            },
            "tokens": self.tokens,
            "agents": self.agents,
            "annotated": self.annotated,
        }

    def line(self) -> str:
        """One prose row: score, mode, id, task — with the parts."""
        task = " ".join(self.task.split())
        if len(task) > 48:
            task = task[:45] + "..."
        mark = " [annotated]" if self.annotated else ""
        return (f"{self.score:5.2f}  {self.mode:<22.22} "
                f"{self.trace_id}  {task}{mark}")


def _trace_agents(trace: Trace) -> List[str]:
    out = []
    for step in trace.steps:
        if step.agent and step.agent not in out:
            out.append(step.agent)
    return out


def triage(
    traces: List[Trace],
    annotated_ids: Optional[set] = None,
) -> List[TriageRow]:
    """Rank the store's failed traces, highest postmortem value first.

    Components (each normalized 0..1 inside the window):
      novelty — 1/(1 + same-mode predecessors) by mode attribution;
                a mode never seen in the window is a full 1.0
      cost    — tokens burned by the failed run vs the window's worst
      blast   — distinct agents on the run vs the window's widest
      recency — position in the window (newest = 1.0)
    Unattributable failures keep their queue spot under mode
    ``unattributed`` — they are exactly the ones needing eyes.
    """
    failures = [t for t in traces if t.success is False]
    if not failures:
        return []
    annotated_ids = annotated_ids or set()
    rows: List[TriageRow] = []
    mode_seen: Dict[str, int] = {}
    for t in failures:
        mode = "unattributed"
        try:
            report = attribute(t)
            if report.failed and report.primary_mode is not None:
                mode = report.primary_mode.id
        except Exception:  # nosec B110 - poison step demotes, never dies
            pass
        seen = mode_seen.get(mode, 0)
        mode_seen[mode] = seen + 1
        rows.append(TriageRow(
            trace_id=t.id,
            task=t.task,
            mode=mode,
            score=0.0,
            novelty=1.0 / (1.0 + seen),
            cost_norm=0.0,
            blast_norm=0.0,
            recency_norm=0.0,
            tokens=sum(s.tokens for s in t.steps),
            agents=_trace_agents(t),
            annotated=t.id in annotated_ids,
        ))
    max_tokens = max((r.tokens for r in rows), default=0) or 1
    max_agents = max((len(r.agents) for r in rows), default=0) or 1
    times = [coerce_epoch(t.created_at) for t in failures]
    t_min, t_max = min(times), max(times)
    span = (t_max - t_min) or 1.0
    for row, created in zip(rows, times, strict=True):
        row.cost_norm = row.tokens / max_tokens
        row.blast_norm = len(row.agents) / max_agents
        row.recency_norm = (created - t_min) / span
        row.score = (W_NOVELTY * row.novelty
                     + W_COST * row.cost_norm
                     + W_BLAST * row.blast_norm
                     + W_RECENCY * row.recency_norm)
    rows.sort(key=lambda r: (-r.score, r.trace_id))
    return rows


def triage_store(store: Any, since_days: Optional[int] = None,
                 unannotated_only: bool = False) -> List[TriageRow]:
    """The CLI/MCP door: windowed, annotation-aware."""
    traces = store.list_traces(since_days=since_days)
    annotated = {a.get("trace_id") for a in store.annotations()
                 if a.get("trace_id")}
    rows = triage(traces, annotated_ids=annotated)
    if unannotated_only:
        rows = [r for r in rows if not r.annotated]
    return rows


def render_queue(rows: List[TriageRow], limit: int = 20) -> str:
    """Prose rendering: the top of the queue plus its accounting."""
    if not rows:
        return "nothing to triage: no failed traces in the window"
    lines = [(f"triage queue ({len(rows)} failed, "
              f"top {min(limit, len(rows))}):")]
    lines.extend("  " + row.line() for row in rows[:limit])
    fresh = sum(1 for r in rows if r.mode != "unattributed"
                and r.novelty == 1.0)
    lines.append(f"  modes: {len({r.mode for r in rows})} distinct, "
                 f"{fresh} first-of-kind in window; "
                 f"{sum(1 for r in rows if r.annotated)} already "
                 f"annotated")
    return "\n".join(lines)
