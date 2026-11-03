"""v364: the demo recorder is a real module, not inline YAML.

agent-gate and agent-audit both need a store to judge; the
recorded fixture used to live as an inline heredoc in each
workflow (duplicated, untestable). It is `examples/record-demo.py`
now — imported and pinned by this test, and the gate it feeds is
verified against the recorded store.
"""

import subprocess
import sys
import tempfile
from pathlib import Path


def test_the_script_records_and_the_gate_passes():
    root = Path(__file__).resolve().parents[1]
    store = Path(tempfile.mkdtemp()) / "s"
    proc = subprocess.run(
        [sys.executable, str(root / "examples" / "record-demo.py"),
         str(store)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    from approximately.store import TraceStore

    traces = TraceStore(store).list_traces()
    assert len(traces) == 3
    assert sum(1 for t in traces if t.success is False) == 1, \
        "two ok runs, one failure: the gate has something to judge"
