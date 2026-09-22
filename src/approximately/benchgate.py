"""Attribution-quality regression gate: labeled dataset + floors -> exit code.

The same gate CI runs on the shipped corpora, callable against any
dataset a user owns: run the rule detectors over an ``approx``-format
JSONL dataset, evaluate set-based P/R/F1, and compare against a floors
file (``sample_f1`` plus a per-mode minimums map, the format of
``docs/bench-floors.json``). Exit 1 on any breach — so a detector or
model change that silently degrades attribution fails the build.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from .distill import check_floors, evaluate_multi, load_dataset


def _non_finite(node, path="$"):
    """Paths of non-finite numbers in a floors document.

    ``json.loads`` happily accepts NaN/Infinity; a NaN floor would
    compare False against every score and silently disable the gate.
    """
    if isinstance(node, float) and not math.isfinite(node):
        return [path]
    if isinstance(node, dict):
        return [bad for k, v in node.items()
                for bad in _non_finite(v, f"{path}.{k}")]
    if isinstance(node, list):
        return [bad for i, v in enumerate(node)
                for bad in _non_finite(v, f"{path}[{i}]")]
    return []


def run_gate(dataset: Path, floors_path: Path, label: str = "gate") -> int:
    labeled = load_dataset(dataset, fmt="jsonl")
    if not labeled:
        print(f"bench-gate[{label}]: no labeled records found",
              file=sys.stderr)
        return 1
    floors = json.loads(floors_path.read_text(encoding="utf-8"))
    corrupt = _non_finite(floors)
    if corrupt:
        print(f"bench-gate[{label}]: floors file has non-finite "
              f"value(s) at {', '.join(corrupt[:5])} — refusing to "
              "run a gate that cannot fail",
              file=sys.stderr)
        return 1
    pairs = [(t, (labels if isinstance(labels, list) else [labels]))
             for t, labels in labeled]
    multi = evaluate_multi(pairs)

    print(f"attribution floors [{label}] - "
          f"{len(pairs)} multi-label records")
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", help="labeled JSONL dataset "
                                        "(approx format)")
    parser.add_argument("--floors", required=True,
                        help="floors JSON (sample_f1 + modes map)")
    parser.add_argument("--label", default="gate",
                        help="name shown in the log prefix")
    args = parser.parse_args(argv)
    return run_gate(Path(args.dataset), Path(args.floors), args.label)


if __name__ == "__main__":
    raise SystemExit(main())
