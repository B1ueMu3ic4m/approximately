"""Built-in 30-second demo: a travel-booking agent that fails three ways.

The run is fully deterministic and needs no API key. It commits three
classic MAST failures on purpose:

- FM-1.3 Step Repetition        — searches the same flights three times
- FM-3.2 No Verification        — books a seat, never confirms the booking
- FM-3.1 Premature Termination  — reports success while the harness fails the run
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

from .attributor import attribute
from .recorder import Recorder
from .store import TraceStore
from .trace import Trace


def _flights(jt_price: int, ke_price: int) -> str:
    return (
        f"JT-044 SFO→NRT 06-14 ${jt_price} 12h40m 1 stop | "
        f"KE-102 SFO→NRT 06-14 ${ke_price} 11h55m 1 stop | "
        f"UA-837 SFO→NRT 06-14 $1040 9h20m nonstop"
    )


def _run_booking_agent(rec: Recorder) -> None:
    rec.plan(
        "Find the cheapest SFO→NRT flight in June (budget $900) and book seat 12A."
    )
    rec.tool(
        "search_flights",
        {"origin": "SFO", "destination": "NRT", "month": "June"},
        result=_flights(870, 912),
        thought="search inventory, then pick the cheapest within budget",
    )
    # failure 1: repeats the same search twice more (prices keep drifting)
    rec.tool(
        "search_flights",
        {"origin": "SFO", "destination": "NRT", "month": "June"},
        result=_flights(875, 918),
        thought="double-check the prices haven't changed",
    )
    rec.tool(
        "search_flights",
        {"origin": "SFO", "destination": "NRT", "month": "June"},
        result=_flights(880, 924),
        thought="one more look to be safe",
    )
    # failure 2 setup: a mutating call...
    rec.tool(
        "book_flight",
        {"flight": "JT-044", "seat": "12A", "price_cap": 900},
        result="BOOKED confirmation #B-2231 (unverified)",
        thought="JT-044 at $870 is under budget",
        mutating=True,
    )
    # ...with no verification step afterwards, and
    # failure 3: declares victory while the harness grades the run failed
    # (seat 12A was never confirmed against the airline's seat map).
    rec.respond(
        "Done! Booked JT-044 SFO→NRT on 06-14, seat 12A, $880 (under your $900 "
        "budget). Confirmation #B-2231.",
        success=False,
    )


def run_demo(store_dir: Optional[Path] = None) -> Tuple[Trace, object, Optional[Path]]:
    """Run the failing agent, attribute, render the HTML report.

    Returns ``(trace, report, report_path)``; ``report_path`` is ``None``
    when saving is disabled.
    """
    store = TraceStore(store_dir) if store_dir else TraceStore()
    with Recorder(
        "Find the cheapest SFO→NRT flight in June and book seat 12A.",
        model="demo/failing-booking-agent",
        store=store,
    ) as rec:
        _run_booking_agent(rec)

    report = attribute(rec.trace)
    path = store.directory / f"{rec.trace.id}.report.html"
    from .report import render_html

    path.write_text(render_html(rec.trace, report), encoding="utf-8")
    return rec.trace, report, path
