"""v172: `replay --json` — the diff as data.

A/B replay verification is scriptable now: `--json` emits both
verdicts plus the step-level diffs as data (asdict of the ReplayDiff),
so a pipeline can gate on `verdict == "diverged"` without parsing
prose. Exit codes unchanged.
"""

import argparse
import json

from approximately.cli import cmd_replay
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed(directory):
    store = TraceStore(directory)
    rec = Recorder("replay me", save=False)
    rec.tool("echo", {"msg": "hello"}, result="hello")
    rec.respond("done", success=True)
    store.save(rec.trace)
    return rec.trace


def test_replay_json_payload(tmp_path, capsys, monkeypatch):
    trace = _seed(tmp_path / "s")

    def echo_ok(step):
        return step.result

    import sys

    module = type(sys)("fake_exec")
    module.run_step = echo_ok
    # monkeypatch auto-removes the module: no leakage into other tests
    monkeypatch.setitem(sys.modules, "fake_exec", module)
    args = argparse.Namespace(store=str(tmp_path / "s"),
                              trace=trace.id,
                              executor="fake_exec:run_step",
                              patched=None, html=None,
                              threshold=0.85, json=True)
    assert cmd_replay(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] in ("consistent", "diverged")
    assert isinstance(payload["steps"], list)
    assert payload["steps"][0]["tool"] == "echo"
