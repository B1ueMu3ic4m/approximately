"""v75: bench-gate ships in the package + reusable GitHub Action.

The gate logic moves from scripts/bench_gate.py into
approximately.benchgate (CLI: ``approximately bench-gate``), so the
reusable action can run it for any caller-owned dataset. The fixtures
under examples/action/ are the same ones the CI dogfood job feeds the
action.
"""

import subprocess
import sys
from pathlib import Path

from approximately.benchgate import run_gate
from approximately.cli import build_parser

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "examples" / "action" / "fixture.jsonl"
FLOORS = ROOT / "examples" / "action" / "floors.json"
IMPOSSIBLE = ROOT / "examples" / "action" / "floors-impossible.json"


def test_gate_passes_on_fixture(capsys):
    assert run_gate(FIXTURE, FLOORS, "selftest") == 0
    out = capsys.readouterr().out
    assert "PASS - no attribution regression" in out
    assert "multi-label records" in out


def test_gate_fails_on_impossible_floor(capsys):
    assert run_gate(FIXTURE, IMPOSSIBLE, "neg") == 1
    assert "no score (required)" in capsys.readouterr().err


def test_gate_empty_dataset_is_an_error(tmp_path, capsys):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n\n", encoding="utf-8")
    assert run_gate(empty, FLOORS, "empty") == 1
    assert "no labeled records" in capsys.readouterr().err


def test_cli_bench_gate_wiring():
    parser = build_parser()
    args = parser.parse_args(
        ["bench-gate", str(FIXTURE), "--floors", str(FLOORS),
         "--label", "wired"])
    assert args.func(args) == 0
    args = parser.parse_args(
        ["bench-gate", str(FIXTURE), "--floors", str(IMPOSSIBLE)])
    assert args.func(args) == 1


def test_script_shim_still_gates_synth():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "bench_gate.py"),
         "--synth"],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0
    assert "attribution floors [synthetic]" in proc.stdout


def test_action_yml_contract():
    action = (ROOT / "action.yml").read_text(encoding="utf-8")
    assert "using: composite" in action
    for expected in ("dataset:", "floors:", "install-from:",
                     "approximately bench-gate"):
        assert expected in action
    assert (ROOT / "examples" / "action" / "floors.json").exists()
    assert (ROOT / "examples" / "action"
            / "floors-impossible.json").exists()
