#!/usr/bin/env python3
"""Attribution performance gate: complexity-regression tripwire.

Attributes every record of the synthetic fixture and asserts the
per-record mean stays under a deliberately generous bound. The bound
is ~25x the observed headroom (2.1 ms/record locally), so ordinary
CI-runner variance cannot trip it — only an algorithmic-complexity
regression (the O(n^2)/backtracking class the fuzz round guards
against) can.

Usage: python scripts/perf_gate.py [--max-ms-per-record 50]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from approximately.attributor import attribute  # noqa: E402
from approximately.distill import load_dataset  # noqa: E402

SYNTH = ROOT / "docs" / "mast-bench-synth.jsonl"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-ms-per-record", type=float, default=50.0,
                        help="per-record attribution budget in "
                             "milliseconds (default 50, ~25x headroom)")
    args = parser.parse_args()
    return (attribution_gate(args) + agent_wave_gate()
            + query_gate() + similar_gate())

def attribution_gate(args) -> int:
    labeled = load_dataset(SYNTH, fmt="approx")
    if not labeled:
        print("perf-gate: no records found", file=sys.stderr)
        return 1
    traces = [t for t, _ in labeled]

    start = time.perf_counter()
    for trace in traces:
        attribute(trace)
    elapsed = time.perf_counter() - start
    per_record_ms = elapsed / len(traces) * 1000

    print(f"perf-gate: attributed {len(traces)} records in "
          f"{elapsed:.2f}s ({per_record_ms:.1f} ms/record, "
          f"budget {args.max_ms_per_record:g} ms)")
    if per_record_ms > args.max_ms_per_record:
        print(f"FAIL: attribution slowed past "
              f"{args.max_ms_per_record:g} ms/record - "
              f"complexity regression?",
              file=sys.stderr)
        return 1
    print("PASS - attribution performance within budget")
    return 0


def agent_wave_gate(budget_s: float = 5.0) -> int:
    """Scorecard + markdown + fleet render on a 10k-step trace.

    The agent wave (v0.50) walks every step per agent and renders
    timelines; this keeps the whole pass linear and bounded.
    """
    from approximately.attributor import attribute
    from approximately.cluster import agent_scorecard
    from approximately.markdown_report import render_markdown
    from approximately.recorder import Recorder

    rec = Recorder("perf: agent wave", save=False, agent="worker")
    rec.tool("bash", {"cmd": "prime"}, result="ok", agent="worker")
    for i in range(10_000):
        rec.tool("bash", {"cmd": f"c{i}"}, result="r", thought="t")
    rec.respond("done", success=False)
    trace = rec.trace

    start = time.perf_counter()
    rows = agent_scorecard([trace])
    render_markdown(trace, attribute(trace))
    elapsed = time.perf_counter() - start
    ok = rows[0]["steps"] == 10_002 and elapsed < budget_s
    print(f"perf-gate[agent-wave]: scorecard+markdown on 10k steps "
          f"in {elapsed:.2f}s (budget {budget_s:.0f}s) - "
          f"{'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1



def query_gate(budget_s: float = 2.0) -> int:
    """Expression filter over a 10k-trace store, heavy field twice.

    ``mode`` mentions used to re-run the detector suite per mention;
    per-select memoization (v0.66) makes it once per trace. This gate
    pins that: the double-mention filter over 10k traces must stay
    linear and bounded.
    """
    from approximately.query import select
    from approximately.recorder import Recorder

    traces = []
    for i in range(10_000):
        ok = i % 3 != 0
        rec = Recorder(f"t {i}", save=False)
        rec.trace.id = f"p-{i}"
        rec.tool("search", {"q": i}, result=None if ok else "x",
                 error=None if ok else "timeout")
        rec.respond("done", success=ok)
        traces.append(rec.trace)

    start = time.perf_counter()
    found = select(traces, "mode == FM-2.1 or mode != FM-2.1")
    elapsed = time.perf_counter() - start
    if len(found) != len(traces):
        print("FAIL: query gate returned the wrong count",
              file=sys.stderr)
        return 1
    print(f"perf-gate[query]: double-mode filter over 10k traces in "
          f"{elapsed * 1000:.0f}ms (budget {budget_s:g}s) - "
          + ("PASS" if elapsed <= budget_s else "FAIL"))
    if elapsed > budget_s:
        print("FAIL: select slowed past budget - memoization regressed?",
              file=sys.stderr)
        return 1
    return 0





def similar_gate(budget_s: float = 2.0) -> int:
    """Nearest-neighbour ranking over a 2000-trace store.

    rank_similar skips the quadratic DP below the top-N threshold
    (v1.4); this gate pins that - the same store ranked in 0.2 s
    after the change and would blow the budget if the pruning
    regressed to per-candidate full scans.
    """
    from approximately.align import rank_similar
    from approximately.recorder import Recorder

    traces = []
    for i in range(2000):
        rec = Recorder(f"t {i}", save=False)
        rec.trace.id = f"big-{i}"
        for j in range(20):
            rec.tool("probe", {"i": j}, result="ok")
        rec.respond("done", success=bool(i % 3))
        traces.append(rec.trace)

    start = time.perf_counter()
    ranked = rank_similar(traces[0], traces, top=5)
    elapsed = time.perf_counter() - start
    if len(ranked) != 5 or any(
            c.id == traces[0].id for c, _ in ranked):
        print("FAIL: similar gate ranked wrong", file=sys.stderr)
        return 1
    print(f"perf-gate[similar]: rank 2000 traces in "
          f"{elapsed:.2f}s (budget {budget_s:g}s) - "
          + ("PASS" if elapsed <= budget_s else "FAIL"))
    if elapsed > budget_s:
        print("FAIL: similar slowed past budget - pruning regressed?",
              file=sys.stderr)
        return 1
    return 0



if __name__ == "__main__":
    raise SystemExit(main())
