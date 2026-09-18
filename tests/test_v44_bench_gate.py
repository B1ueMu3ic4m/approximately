"""v0.44 — attribution-quality regression floors (bench gate)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from approximately.distill import check_floors, evaluate_multi

CORPUS = Path(__file__).resolve().parent.parent / "docs" / "mast-bench-multi.jsonl"
FLOORS = Path(__file__).resolve().parent.parent / "docs" / "bench-floors.json"


def _multi(per_mode=None, macro_f1=0.5):
    return SimpleNamespace(per_mode=per_mode or {}, macro_f1=macro_f1)


def test_no_violations_when_floors_met():
    floors = {"sample_f1": 0.4,
              "modes": {"FM-2.1": {"precision": 0.9, "recall": 0.9}}}
    multi = _multi({"FM-2.1": {"precision": 0.93, "recall": 1.0,
                               "f1": 0.96}}, macro_f1=0.46)
    assert check_floors(multi, floors) == []


def test_precision_recall_and_f1_breaches_reported():
    floors = {"modes": {"FM-1.3": {"precision": 0.9, "recall": 0.6,
                                   "f1": 0.7}}}
    multi = _multi({"FM-1.3": {"precision": 0.5, "recall": 0.5,
                               "f1": 0.5}})
    violations = check_floors(multi, floors)
    assert len(violations) == 3
    assert any("precision 0.50" in v for v in violations)


def test_missing_mode_only_fails_when_required():
    floors = {"modes": {"FM-2.3": {"required": True}}}
    assert check_floors(_multi(), floors) == ["FM-2.3: no score (required)"]
    floors_optional = {"modes": {"FM-2.3": {"precision": 0.5}}}
    assert check_floors(_multi(), floors_optional) == []


def test_sample_macro_f1_floor():
    floors = {"sample_f1": 0.44}
    violations = check_floors(_multi(macro_f1=0.43), floors)
    assert violations == ["sample macro-F1 0.43 < floor 0.44"]


def test_floors_doc_is_valid_and_current():
    floors = json.loads(FLOORS.read_text(encoding="utf-8"))
    assert isinstance(floors.get("sample_f1"), float)
    assert floors["modes"]["FM-2.1"]["recall"] >= 0.9


def test_corpus_clears_floors():
    """The shipped corpus must clear the shipped floors (CI parity)."""
    from approximately.trace import Trace

    if not CORPUS.exists():
        return  # docs material, not a package dependency
    pairs = []
    for line in CORPUS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        labels = raw.pop("labels")
        pairs.append((Trace.from_dict(raw), labels))
    violations = check_floors(evaluate_multi(pairs),
                              json.loads(FLOORS.read_text(encoding="utf-8")))
    assert violations == []
