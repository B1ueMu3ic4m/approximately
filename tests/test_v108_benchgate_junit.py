"""v108: bench-gate JUnit export — CI reporters render gates natively.

`bench_gate.run_gate(..., junit_path=...)` (and the CLI `--junit` /
script `--junit`) writes one testcase per guarded floor: sample_f1
plus each mode's precision/recall/f1. A violation becomes a JUnit
failure whose message carries actual vs floor — the CI annotation
says what regressed. `xml.etree` escapes names, so `>=` in case
names is data, not markup.
"""

import xml.etree.ElementTree as ET
from pathlib import Path

from approximately.benchgate import junit_xml

GOLD = {
    "records": 27,
    "modes": {
        "FM-1.3": {"precision": 1.0, "recall": 0.71, "f1": 0.83},
        "FM-2.1": {"precision": 0.93, "recall": 1.0, "f1": 0.96},
    },
    "sample_f1": 0.46,
    "violations": [],
    "passed": True,
    "_floors": {
        "sample_f1": 0.44,
        "modes": {"FM-1.3": {"precision": 0.9, "recall": 0.6,
                             "f1": 0.55},
                  "FM-2.1": {"precision": 0.9, "recall": 0.9}},
    },
}


def _suite(xml_text):
    return ET.fromstring(xml_text)


def test_all_passing_floors_are_testcases():
    suite = _suite(junit_xml(GOLD, label="gold"))
    assert suite.get("failures") == "0"
    assert int(suite.get("tests")) == 6  # sample_f1 + 3 (FM-1.3) + 2 (FM-2.1)
    names = [c.get("name") for c in suite]
    assert "sample_f1 >= 0.44" in names
    assert "FM-2.1.recall >= 0.9" in names


def test_violated_floor_becomes_failure_with_message():
    broken = {**GOLD, "sample_f1": 0.40, "passed": False,
              "violations": ["sample macro-F1 0.40 < 0.44"]}
    suite = _suite(junit_xml(broken))
    assert suite.get("failures") == "1"
    case = next(c for c in suite
                if c.get("name") == "sample_f1 >= 0.44")
    failure = case.find("failure")
    assert "0.4" in failure.get("message")
    assert "0.44" in failure.get("message")


def test_missing_mode_scores_fail_their_floors():
    """A mode the detector stopped finding must fail loudly, not pass."""
    partial = {**GOLD, "modes": {k: v for k, v in GOLD["modes"].items()
                                 if k != "FM-2.1"}}
    suite = _suite(junit_xml(partial))
    failures = suite.get("failures")
    assert failures == "2"  # FM-2.1 precision + recall floors unmet
    messages = " ".join(c.find("failure").get("message")
                        for c in suite if c.find("failure") is not None)
    assert "actual None" in messages


def test_xml_escapes_case_names():
    suite = _suite(junit_xml(GOLD))
    # ET renders '>=' as &gt;= in attribute values; parse-back equals
    names = [c.get("name") for c in suite]
    assert any(">=" in n for n in names)


def test_run_gate_writes_junit(tmp_path):
    from pathlib import Path

    from approximately.benchgate import run_gate

    out = tmp_path / "gate.xml"
    root = Path(__file__).resolve().parents[1]
    rc = run_gate(root / "docs" / "mast-bench-multi.jsonl",
                  root / "docs" / "bench-floors.json",
                  "test-gate", junit_path=out)
    assert rc == 0
    suite = ET.parse(out).getroot()
    assert suite.get("name") == "approximately.bench-gate[test-gate]"
    assert suite.get("failures") == "0"


def test_min_records_fails_shrunken_dataset(tmp_path):
    """v1.11: a dataset that shrank below min_records fails loudly -
    a small sample can pass any floor by luck."""
    import json as _json

    from approximately.benchgate import gate_result

    root = Path(__file__).resolve().parents[1]
    floors = {
        **_json.loads((root / "docs" / "bench-floors.json")
                      .read_text(encoding="utf-8")),
        "min_records": 10_000,
    }
    floors_path = tmp_path / "floors.json"
    floors_path.write_text(_json.dumps(floors), encoding="utf-8")
    result = gate_result(root / "docs" / "mast-bench-multi.jsonl",
                         floors_path)
    assert result["passed"] is False
    assert any("min_records" in v for v in result["violations"])
