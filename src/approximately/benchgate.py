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
from typing import Optional

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


def gate_result(dataset: Path, floors_path: Path) -> dict:
    """Evaluate a dataset against floors; structured, print-free.

    Raises ``ValueError`` on empty datasets and non-finite floors
    (the corruption case: a NaN floor compares False against every
    score and would silently disable the gate).
    """
    labeled = load_dataset(dataset, fmt="jsonl")
    if not labeled:
        raise ValueError(f"no labeled records found in {dataset}")
    floors = json.loads(floors_path.read_text(encoding="utf-8"))
    if not isinstance(floors, dict):
        raise ValueError("floors file must be a JSON object")
    corrupt = _non_finite(floors)
    if corrupt:
        raise ValueError("floors file has non-finite value(s) at "
                         f"{', '.join(corrupt[:5])} — refusing to "
                         "run a gate that cannot fail")
    pairs = [(t, (labels if isinstance(labels, list) else [labels]))
             for t, labels in labeled]
    multi = evaluate_multi(pairs)
    violations = check_floors(multi, floors)
    min_records = floors.get("min_records")
    if min_records is not None and len(pairs) < int(min_records):
        shrink = (f"records {len(pairs)} < min_records {min_records} "
                  "- the dataset itself shrank; a small sample can "
                  "pass any floor by luck")
        violations = [*violations, shrink]
    return {
        "records": len(pairs),
        "modes": {mode: {
            "precision": round(m["precision"], 4),
            "recall": round(m["recall"], 4),
            "f1": round(m["f1"], 4),
        } for mode, m in (multi.per_mode or {}).items()},
        "sample_f1": round(multi.macro_f1, 4),
        "violations": violations,
        "passed": not violations,
    }


def run_gate(dataset: Path, floors_path: Path, label: str = "gate",
             junit_path: Optional[Path] = None) -> int:
    try:
        result = gate_result(dataset, floors_path)
    except ValueError as exc:
        print(f"bench-gate[{label}]: {exc}", file=sys.stderr)
        return 1
    floors = json.loads(floors_path.read_text(encoding="utf-8"))
    result["_floors"] = floors

    print(f"attribution floors [{label}] - "
          f"{result['records']} multi-label records")
    for mode, spec in sorted((floors.get("modes") or {}).items()):
        m = result["modes"].get(mode)
        if m is None:
            state = "no score"
        else:
            state = (f"P {m['precision']:.2f}/"
                     f"{spec.get('precision', 0):.2f} "
                     f"R {m['recall']:.2f}/"
                     f"{spec.get('recall', 0):.2f} "
                     f"F1 {m['f1']:.2f}")
        print(f"  {mode:<7} {state}")
    print(f"  sample macro-F1 {result['sample_f1']:.2f}/"
          f"{floors.get('sample_f1', 0):.2f}")

    if result["violations"]:
        for violation in result["violations"]:
            print(f"FAIL {violation}", file=sys.stderr)
        return 1
    print("PASS - no attribution regression")
    if junit_path is not None:
        write_junit(result, junit_path, label=label)
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


def junit_xml(result: dict, label: str = "gate") -> str:
    """A gate result as JUnit XML — CI test reporters render it natively.

    One testcase per floor: sample_f1 plus each mode's P/R/F1.
    A testcase fails when the floor it guards is violated; the
    failure message carries actual vs floor so the CI annotation
    says what regressed, not just "gate failed".
    """
    import xml.etree.ElementTree as ET  # nosec B405 - emit-only, no untrusted XML parsed

    floors = result.get("_floors") or {}
    suite = ET.Element("testsuite", {
        "name": f"approximately.bench-gate[{label}]",
        "tests": "0", "failures": "0",
    })

    def add(name, failed, message=""):
        suite.set("tests", str(int(suite.get("tests")) + 1))
        case = ET.SubElement(suite, "testcase", {
            "name": name, "classname": "approximately.bench_gate",
        })
        if failed:
            suite.set("failures", str(int(suite.get("failures")) + 1))
            ET.SubElement(case, "failure", {"message": message})

    floor_sample = floors.get("sample_f1")
    if floor_sample is not None:
        actual = result.get("sample_f1")
        add(f"sample_f1 >= {floor_sample}",
            actual is None or actual < floor_sample,
            f"actual {actual} < floor {floor_sample}")
    for mode, spec in sorted((floors.get("modes") or {}).items()):
        actual = (result.get("modes") or {}).get(mode) or {}
        for metric in ("precision", "recall", "f1"):
            floor = (spec or {}).get(metric)
            if floor is None:
                continue
            value = actual.get(metric)
            add(f"{mode}.{metric} >= {floor}",
                value is None or value < floor,
                f"actual {value} < floor {floor}")
    return ET.tostring(suite, encoding="unicode") + "\n"


def write_junit(result: dict, path: Path, label: str = "gate") -> Path:
    """Persist the JUnit rendering; the result dict may carry _floors."""
    path.write_text(junit_xml(result, label=label), encoding="utf-8")
    return path
