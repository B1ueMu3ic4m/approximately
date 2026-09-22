#!/usr/bin/env python3
"""Attribution-quality regression gate on the shipped gold corpus.

Thin shim over :mod:`approximately.benchgate` (the gate itself ships
in the package as ``approximately bench-gate``), keeping this script's
historical ``--synth`` flag and corpus paths for existing CI and docs.

Zero dependencies beyond the package itself; stdlib only here.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from approximately.benchgate import run_gate  # noqa: E402

CORPUS = ROOT / "docs" / "mast-bench-multi.jsonl"
FLOORS = ROOT / "docs" / "bench-floors.json"
SYNTH_CORPUS = ROOT / "docs" / "mast-bench-synth.jsonl"
SYNTH_FLOORS = ROOT / "docs" / "bench-synth-floors.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synth", action="store_true",
                        help="gate the synthetic fixture instead of "
                             "the gold corpus")
    args = parser.parse_args()
    if args.synth:
        return run_gate(SYNTH_CORPUS, SYNTH_FLOORS, "synthetic")
    return run_gate(CORPUS, FLOORS, "gold corpus")


if __name__ == "__main__":
    raise SystemExit(main())
