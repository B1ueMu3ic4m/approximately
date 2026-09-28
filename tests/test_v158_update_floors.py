"""v158: floors that keep up — `bench-gate --update-floors`.

After an intentional improvement (or a corpus change), the floors file
goes stale: the gate passes forever or fails forever.
`--update-floors` regenerates it from a measured run at
measured-minus-margin — headroom for noise, not a pass-everything
gate. `min_records` survives unless explicitly set.
"""

import argparse
import json

from approximately.benchgate import gate_result, update_floors
from approximately.cli import cmd_bench_gate


def test_update_floors_writes_measured_minus_margin(tmp_path):
    floors = tmp_path / "floors.json"
    floors.write_text(json.dumps({"sample_f1": 0.0, "modes": {}}),
                      encoding="utf-8")
    result = update_floors(docs_dataset(), floors, margin=0.05)
    written = json.loads(floors.read_text(encoding="utf-8"))
    assert result["records"] > 0
    assert written["_comment"].startswith("Regression floors")
    for spec in written["modes"].values():
        for value in spec.values():
            assert 0.0 <= value <= 1.0
    # and the regenerated floors pass a fresh gate
    gate = gate_result(docs_dataset(), floors)
    assert gate["passed"] is True


def docs_dataset():
    from pathlib import Path

    return Path("docs/mast-bench-multi.jsonl")


def test_min_records_survives_regeneration(tmp_path):
    dataset = docs_dataset()
    floors = tmp_path / "floors.json"
    floors.write_text(json.dumps({"sample_f1": 0.0, "modes": {},
                                  "min_records": 5}),
                      encoding="utf-8")
    update_floors(dataset, floors, margin=0.05)
    written = json.loads(floors.read_text(encoding="utf-8"))
    assert written["min_records"] == 5


def test_cli_update_floors_then_gate(tmp_path, capsys):
    dataset = "docs/mast-bench-multi.jsonl"
    floors = tmp_path / "floors.json"
    floors.write_text(json.dumps({"sample_f1": 0.0, "modes": {}}),
                      encoding="utf-8")
    update_args = argparse.Namespace(
        dataset=dataset, floors=str(floors), update_floors=True,
        margin=0.05, min_records=None, label="gold", junit=None,
        json=False)
    assert cmd_bench_gate(update_args) == 0
    assert "floors regenerated" in capsys.readouterr().out
    gate_args = argparse.Namespace(
        dataset=dataset, floors=str(floors), update_floors=False,
        margin=0.05, min_records=None, label="gold", junit=None,
        json=True)
    assert cmd_bench_gate(gate_args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is True
