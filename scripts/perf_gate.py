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


if __name__ == "__main__":
    raise SystemExit(main())
