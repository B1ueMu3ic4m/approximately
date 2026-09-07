"""Standalone example: record a failing agent, attribute, generate a report.

Run:
    python examples/flaky_agent.py

No API key needed — the agent is scripted and deterministic, and attribution
runs on the rule detectors. It fails in three classic MAST ways:

- FM-1.3 Step Repetition        — same search three times
- FM-3.2 No Verification        — books a seat, never confirms
- FM-3.1 Premature Termination  — claims success while the harness fails it
"""

from pathlib import Path

from approximately import Recorder, attribute, render_html
from approximately.store import TraceStore


# @agentstep auto-records decorated calls into the current recorder.
# Without an active recorder the function is a plain function.
def search_flights(origin: str, destination: str, day: str) -> str:
    from approximately import current_recorder

    result = f"JT-044 {origin}->{destination} {day} $880 | KE-102 $924"
    rec = current_recorder()
    if rec:
        rec.tool("search_flights",
                 {"origin": origin, "destination": destination, "day": day},
                 result=result)
    return result


def main() -> None:
    store = TraceStore(Path.home() / ".approximately" / "traces")

    with Recorder("Book the cheapest SFO-NRT flight, seat 12A, under $900.",
                  model="example/flaky-agent", store=store) as rec:
        rec.plan("search, pick cheapest under $900, book 12A, verify booking")
        search_flights("SFO", "NRT", "06-14")
        search_flights("SFO", "NRT", "06-14")   # FM-1.3: identical repeat
        rec.tool("book_flight", {"flight": "JT-044", "seat": "12A"},
                 result="BOOKED confirmation #B-7742",
                 mutating=True)                  # FM-3.2: never verified
        rec.respond("All set! JT-044, seat 12A, $880.",
                    success=False)               # FM-3.1: harness says failed

    report = attribute(rec.trace)
    print(report.summary)
    for det in report.detections:
        print(f"  - {det.mode_id} at step #{det.step_index} "
              f"({det.source}, confidence {det.confidence:.2f})")

    out = Path(f"report_{rec.trace.id}.html")
    out.write_text(render_html(rec.trace, report), encoding="utf-8")
    print(f"HTML report: {out.resolve()}")


if __name__ == "__main__":
    main()
