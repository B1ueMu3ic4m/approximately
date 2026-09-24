"""v91: the perf gate covers the agent wave's step-heavy paths.

scorecard + markdown render on a 10k-step trace must stay linear and
inside the CI budget; the gate script asserts it on every run.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_perf_gate_covers_agent_wave():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "perf_gate.py")],
        capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0
    assert "PASS - attribution performance within budget" in proc.stdout
    assert "perf-gate[agent-wave]" in proc.stdout
    assert "- PASS" in proc.stdout
