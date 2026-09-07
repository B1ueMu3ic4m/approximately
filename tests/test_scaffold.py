"""Tests for the scaffold generator."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from approximately.cli import main
from approximately.scaffold import scaffold


def test_scaffold_creates_expected_files(tmp_path):
    target = scaffold("myagent", base=tmp_path)
    assert (target / "agent.py").exists()
    assert (target / "test_agent_regressions.py").exists()
    assert (target / "README.md").read_text(encoding="utf-8").count("myagent") >= 2


def test_scaffolded_agent_compiles_and_runs(tmp_path):
    target = scaffold("ag", base=tmp_path)
    compile((target / "agent.py").read_text(encoding="utf-8"), "agent.py", "exec")
    result = subprocess.run(
        [sys.executable, str(target / "agent.py")],
        capture_output=True, text=True, timeout=60,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path),
             "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
             "APPROXIMATELY_HOME": str(tmp_path / "traces")},
    )
    assert result.returncode == 0, result.stderr
    assert "report:" in result.stdout


def test_cli_new(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    code = main(["new", "crew_bot"])
    out = capsys.readouterr().out
    assert code == 0
    assert (tmp_path / "crew_bot" / "agent.py").exists()
    assert "created" in out


def test_scaffold_is_idempotent_friendly(tmp_path):
    scaffold("ag", base=tmp_path)
    scaffold("ag", base=tmp_path)  # second run overwrites, no crash
    assert (tmp_path / "ag" / "agent.py").exists()
