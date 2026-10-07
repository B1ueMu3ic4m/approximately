"""Value-weighted retention: what postmortem value says to keep.

``clean`` deletes by age alone — a failed run and a boring success
rot identically. Retention keeps the two apart: successes age out on
``keep_days``, failures (and runs whose outcome was never recorded —
an unknown outcome is a question, and retention keeps questions
alive) live on to ``failure_days``. Two guards veto every retirement:
breach evidence (the same stamped guard ``clean --keep-breached``
uses) and annotated traces (a human looked at it). The plan is the
default output — ``--apply`` deletes, and re-checks both guards per
file at apply time, because a plan is a snapshot and the store moves
on. Unreadable files are never touched here: poison is
``doctor --fix``'s job, and a housekeeping pass must not guess.

Attribution mode is deliberately not a signal: re-attributing every
file on a housekeeping pass spends the budget retention is meant to
save; ``triage`` already ranks by value for the human.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

SECONDS_PER_DAY = 86400.0


def _load_trace(store: Any, path: Any) -> Optional[Any]:
    """The file's trace, or None when unreadable — poison is counted,
    never touched."""
    try:
        return store.load(path.stem)
    except Exception:
        return None


def retention_plan(store: Any,
                   keep_days: int,
                   failure_days: Optional[int] = None,
                   now: Optional[float] = None) -> dict:
    """The keep/retire ledger. Never deletes: callers print it or
    hand it to :func:`apply_plan`. ``failure_days`` defaults to
    ``keep_days``; sub-day windows are a refusal (ValueError)."""
    from .store import STORE_ARTIFACTS

    if int(keep_days) < 1:
        raise ValueError("keep_days must be >= 1")
    f_days = int(failure_days if failure_days is not None
                 else keep_days)
    if f_days < 1:
        raise ValueError("failure_days must be >= 1")
    now = now if now is not None else time.time()
    annotated = {a.get("trace_id") for a in store.annotations()
                 if a.get("trace_id")}
    retire: List[Dict[str, Any]] = []
    kept: Dict[str, int] = {"fresh": 0, "failure_young": 0,
                            "protected_breached": 0,
                            "protected_annotated": 0,
                            "unreadable": 0}
    for path in store.directory.glob("*.json"):
        if path.name in STORE_ARTIFACTS:
            continue
        verdict, why = _classify(store, path, annotated,
                                 int(keep_days), f_days, now)
        if verdict is None:
            retire.append({"id": path.stem, "why": why})
        else:
            kept[verdict] += 1
    return {"store": str(store.directory),
            "policy": {"keep_days": int(keep_days),
                       "failure_days": f_days,
                       "guards": ["breached", "annotated"]},
            "retire": retire, "kept": kept}


def _classify(store: Any, path: Any, annotated: set,
              keep_days: int, f_days: int,
              now: float) -> tuple:
    """(kept-key, None) when the file stays, (None, why) when it is
    retirement material — age policy picks candidates, the two
    guards veto."""
    from .store import stamped_breach
    from .trace import coerce_epoch

    trace = _load_trace(store, path)
    if trace is None:
        return "unreadable", None
    age = max(0.0, (now - coerce_epoch(trace.created_at))
              / SECONDS_PER_DAY)
    if trace.success is False or trace.success is None:
        if age < f_days:
            return "failure_young", None
        why = f"failure past {f_days}d"
    else:
        if age < keep_days:
            return "fresh", None
        why = f"success past {keep_days}d"
    if stamped_breach(trace.meta):
        return "protected_breached", None
    if path.stem in annotated:
        return "protected_annotated", None
    return None, why


def apply_plan(store: Any, plan: dict) -> int:
    """Delete the plan's rows, re-checking both guards per file.
    Returns the removed count."""
    from .store import STORE_ARTIFACTS, stamped_breach

    removed = 0
    for row in plan.get("retire", []):
        path = store.directory / f"{row['id']}.json"
        if path.name in STORE_ARTIFACTS or not path.is_file():
            continue
        try:
            trace = store.load(row["id"])
        except Exception:
            trace = None
        if trace is not None:
            if stamped_breach(trace.meta):
                continue
            if store.annotations(trace.id):
                continue
        path.unlink()
        removed += 1
    return removed
