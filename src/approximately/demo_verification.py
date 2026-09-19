"""Verification scenario: a fix claimed done, never verified.

Showcases outcome-level verification analysis (FM-3.2, v0.31): the
final message claims the issue is resolved, the record contains zero
outcome signals (no "N passed/failed", no tracebacks) — an unchecked
claim, exactly the shape the prose outcome-verify detector exists for.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

from .attributor import attribute
from .recorder import Recorder
from .store import TraceStore
from .trace import Trace

_TASK = ("Fix the checkout 500 on empty carts reported by support "
         "ticket #4821.")


def run_demo(store_dir: Optional[Path] = None
             ) -> Tuple[Trace, object, Optional[Path]]:
    store = TraceStore(store_dir) if store_dir else TraceStore()
    with Recorder(_TASK, model="demo/checkout-fixer", store=store) as rec:
        # the scenario mirrors a prose-shaped harness record: turns are
        # narratives, so the prose detector family owns attribution
        rec.trace.meta["prose"] = True
        rec.tool("read_file", {"path": "cart/views.py"},
                 result="def checkout(request): ... total = sum(items)")
        rec.tool("edit_file", {"path": "cart/views.py"},
                 result="added the empty-cart guard at the top")
        rec.tool("read_file", {"path": "cart/tests.py"},
                 result="existing tests for the discount path")
        rec.respond("These changes have successfully fixed the checkout "
                    "500 on empty carts.", success=False)

    report = attribute(rec.trace)
    path = store.directory / f"{rec.trace.id}.report.html"
    from .report import render_html

    path.write_text(render_html(rec.trace, report), encoding="utf-8")
    return rec.trace, report, path
