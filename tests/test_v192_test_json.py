"""v192: `test --json` — the regression scaffold as data.

`approximately test` generates a pytest scaffold for one trace;
`--json` emits where it landed, the attributed mode and the next
step, so a pipeline can wire and run it programmatically.
"""

import argparse
import json

from approximately.cli import cmd_test
from approximately.recorder import Recorder
from approximately.store import TraceStore


def test_test_json(tmp_path, capsys):
    store = TraceStore(tmp_path / "s")
    rec = Recorder("regress me", save=False)
    rec.tool("deploy", {"env": "prod"}, result=None, error="timeout")
    rec.respond("gave up", success=False)
    store.save(rec.trace)
    out = tmp_path / "test_out.py"
    args = argparse.Namespace(store=str(store.directory),
                              trace=rec.trace.id, output=str(out),
                              budget=None, min_recall=0.5, json=True)
    assert cmd_test(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["output"] == str(out)
    assert out.is_file()
    assert "primary_mode" in payload
