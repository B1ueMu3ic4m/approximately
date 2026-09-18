#!/usr/bin/env python3
"""Attribution-quality regression gate on the shipped gold corpus.

Runs the rule detectors over docs/mast-bench-multi.jsonl and compares
per-mode precision/recall/F1 and sample macro-F1 against the floors in
docs/bench-floors.json. Exit 1 on any breach — a detector change that
silently degrades attribution quality fails CI instead of shipping.

Zero dependencies beyond the package itself; stdlib only here.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from approximately.distill import (  # noqa: E402
    check_floors,
    evaluate_multi,
    load_dataset,
)

CORPUS = ROOT / "docs" / "mast-bench-multi.jsonl"
FLOORS = ROOT / "docs" / "bench-floors.json"


def main() -> int:
    labeled = load_dataset(CORPUS, fmt="jsonl")
    if not labeled:
        print("bench-gate: no labeled records found", file=sys.stderr)
        return 1
    pairs = [(t, (labels if isinstance(labels, list) else [labels]))
             for t, labels in labeled]
    multi = evaluate_multi(pairs)
    floors = json.loads(FLOORS.read_text(encoding="utf-8"))

    print(f"attribution floors - {len(pairs)} multi-label records")
    for mode, spec in sorted((floors.get("modes") or {}).items()):
        m = multi.per_mode.get(mode)
        if m is None:
            state = "no score"
        else:
            state = (f"P {m['precision']:.2f}/"
                     f"{spec.get('precision', 0):.2f} "
                     f"R {m['recall']:.2f}/"
                     f"{spec.get('recall', 0):.2f} "
                     f"F1 {m['f1']:.2f}")
        print(f"  {mode:<7} {state}")
    print(f"  sample macro-F1 {multi.macro_f1:.2f}/"
          f"{floors.get('sample_f1', 0):.2f}")

    violations = check_floors(multi, floors)
    if violations:
        for violation in violations:
            print(f"FAIL {violation}", file=sys.stderr)
        return 1
    print("PASS - no attribution regression")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
