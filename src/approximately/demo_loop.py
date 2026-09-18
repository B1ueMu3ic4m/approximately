"""Loop scenario: a multi-agent crew stuck in a cycle.

Showcases cycle-grade repetition detection (FM-1.3): an inner
planner -> navigator -> editor loop whose args evolve every turn, so
exact-fingerprint repetition never fires — the repeated tool
*sequence* is the signal.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

from .attributor import attribute
from .recorder import Recorder
from .store import TraceStore
from .trace import Trace

_TASK = ("Refactor the payment retry logic in the checkout service "
         "(planner/navigator/editor crew).")


def _crew_turn(rec: Recorder, turn: int) -> None:
    # each inner agent sees the growing thread: args differ every
    # turn, the tool sequence repeats — exactly the loop shape the
    # exact-fingerprint RepeatDetector cannot see
    thread = f"turn {turn}: " + " | ".join(
        f"step {i} notes" for i in range(max(1, turn - 3), turn + 1))
    rec.tool("planner", {"thread": thread, "goal": _TASK,
                         "turn": turn},
             result=f"plan v{turn}: keep circling the retry tests")
    rec.tool("navigator", {"thread": thread + " + plan",
                           "turn": turn},
             result=f"route {turn}: check retry_test.py again")
    rec.tool("editor", {"thread": thread + " + route",
                        "patch": f"try {turn}"},
             result=f"patched attempt {turn}: no test run")


def run_demo(store_dir: Optional[Path] = None
             ) -> Tuple[Trace, object, Optional[Path]]:
    store = TraceStore(store_dir) if store_dir else TraceStore()
    with Recorder(_TASK, model="demo/payment-refactor-crew",
                  store=store) as rec:
        for turn in range(1, 9):
            _crew_turn(rec, turn)
        rec.respond("We believe the retry logic is fixed.",
                    success=False)

    report = attribute(rec.trace)
    path = store.directory / f"{rec.trace.id}.report.html"
    from .report import render_html

    path.write_text(render_html(rec.trace, report), encoding="utf-8")
    return rec.trace, report, path
