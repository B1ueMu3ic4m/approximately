"""v139: `status --watch` — the overview that stays up all night.

Night ops want the overview to re-render on an interval, not to run
once and die. `--watch` loops the same frame the one-shot prints;
`--frames` bounds the loop for tests and cron wrappers; Ctrl-C is a
clean exit 0.
"""

import argparse
import json

from approximately.cli import cmd_status
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed(tmp_path, task):
    store = TraceStore(tmp_path / "s")
    rec = Recorder(task, save=False)
    rec.respond("done", success=True)
    store.save(rec.trace)
    return store


def test_watch_renders_frames_and_stops(tmp_path, capsys):
    _seed(tmp_path, "watched run")
    args = argparse.Namespace(store=str(tmp_path / "s"), since=None,
                              digest_dir=None, json=False,
                              watch=True, interval=0.0, frames=3)
    assert cmd_status(args) == 0
    out = capsys.readouterr().out
    assert out.count("=== ") == 3
    assert out.count("1 traces, 0 failed") == 3


def test_watch_json_frames(tmp_path, capsys):
    _seed(tmp_path, "json watch")
    args = argparse.Namespace(store=str(tmp_path / "s"), since=None,
                              digest_dir=None, json=True,
                              watch=True, interval=0.0, frames=2)
    assert cmd_status(args) == 0
    out = capsys.readouterr().out
    frames = [f for f in out.split("=== ") if f.strip()]
    assert len(frames) == 2
    payloads = [json.loads(f.split("===\n", 1)[1]) for f in frames]
    assert all(p["traces"] == 1 for p in payloads)


def test_one_shot_mode_unchanged(tmp_path, capsys):
    _seed(tmp_path, "one shot")
    args = argparse.Namespace(store=str(tmp_path / "s"), since=None,
                              digest_dir=None, json=False,
                              watch=False, interval=30.0, frames=None)
    assert cmd_status(args) == 0
    out = capsys.readouterr().out
    assert out.count("=== ") == 0
    assert "1 traces, 0 failed" in out
