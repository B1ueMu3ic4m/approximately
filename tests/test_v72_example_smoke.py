"""v0.72 — the shipped example runs end to end, isolated."""

import os
import subprocess
import sys
from pathlib import Path

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "flaky_agent.py"


def test_example_runs_and_writes_report_into_store(tmp_path):
    env = dict(os.environ, APPROXIMATELY_HOME=str(tmp_path / "traces"))
    result = subprocess.run([sys.executable, str(EXAMPLE)],
                            capture_output=True, text=True, env=env,
                            timeout=60)
    assert result.returncode == 0, result.stderr
    assert "FM-1.3" in result.stdout
    reports = list((tmp_path / "traces").glob("report_*.html"))
    assert reports, "example report missing from the store"
    # and nothing leaks into the checkout
    repo_root = EXAMPLE.parent.parent
    assert not list(repo_root.glob("report_*.html"))
