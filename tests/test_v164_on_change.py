"""v164: `status --watch --on-change` — no more identical spam.

Long watches print the same frame every interval; with `--on-change`
an unchanged payload suppresses the print (frames still count, so
`--frames` still bounds the loop), and the next change prints again.
"""

import argparse
import threading

from approximately.cli import cmd_status
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed(directory, task):
    store = TraceStore(directory)
    rec = Recorder(task, save=False)
    rec.respond("done", success=True)
    store.save(rec.trace)
    return store


def test_unchanged_frames_are_suppressed(tmp_path, capsys):
    _seed(tmp_path / "s", "quiet store")
    args = argparse.Namespace(store=str(tmp_path / "s"), since=None,
                              digest_dir=None, json=False,
                              watch=True, interval=0.0, frames=4,
                              on_change=True,
                              fail_on_anomalies=False,
                              fail_on_worsening=False)
    assert cmd_status(args) == 0
    out = capsys.readouterr().out
    assert out.count("=== ") == 1  # first frame only
    assert out.count("1 traces, 0 failed") == 1


def test_change_prints_again(tmp_path):
    store = _seed(tmp_path / "s", "changing store")

    def mutate():
        rec = Recorder("the new failure", save=False)
        rec.respond("nope", success=False)
        store.save(rec.trace)

    timer = threading.Timer(0.05, mutate)
    timer.start()
    args = argparse.Namespace(store=str(store.directory), since=None,
                              digest_dir=None, json=False,
                              watch=True, interval=0.02, frames=6,
                              on_change=True,
                              fail_on_anomalies=False,
                              fail_on_worsening=False)
    assert cmd_status(args) == 0
    timer.join()


def test_without_on_change_still_spams(tmp_path, capsys):
    _seed(tmp_path / "s", "spammy")
    args = argparse.Namespace(store=str(tmp_path / "s"), since=None,
                              digest_dir=None, json=False,
                              watch=True, interval=0.0, frames=3,
                              on_change=False,
                              fail_on_anomalies=False,
                              fail_on_worsening=False)
    assert cmd_status(args) == 0
    assert capsys.readouterr().out.count("=== ") == 3
