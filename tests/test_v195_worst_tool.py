"""v195: `status` names the worst tool.

The glance names the top recidivist agent; now it names the worst
tool too — the action-side twin. A tool whose trace failure rate is
>= 50% (with at least two traces of evidence) shows in the payload
and the prose; quiet tools stay quiet.
"""

import argparse

from approximately.cli import _status_payload, cmd_status
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed(directory):
    store = TraceStore(directory)
    # deploy fails 2 of 2; search is clean
    for i in range(2):
        rec = Recorder(f"deploy run {i}", save=False)
        rec.tool("deploy", {"env": "prod"}, result=None,
                 error="timeout")
        rec.respond("gave up", success=False)
        store.save(rec.trace)
    for i in range(2):
        rec = Recorder(f"search run {i}", save=False)
        rec.tool("search", {"q": str(i)}, result="hit")
        rec.respond("done", success=True)
        store.save(rec.trace)
    return store


def test_worst_tool_in_payload(tmp_path):
    store = _seed(tmp_path / "s")
    payload = _status_payload(store, store.list_traces(), None, None)
    worst = payload["worst_tool"]
    assert worst["tool"] == "deploy"
    assert worst["failed_traces"] == 2
    assert worst["failure_rate"] == 1.0


def test_prose_names_it_when_over_half(tmp_path, capsys):
    _seed(tmp_path / "s")
    args = argparse.Namespace(store=str(tmp_path / "s"), since=None,
                              digest_dir=None, json=False,
                              watch=False, interval=30.0, frames=None)
    assert cmd_status(args) == 0
    assert "worst tool: deploy (2/2 runs failed)" in \
        capsys.readouterr().out


def test_quiet_tools_stay_quiet(tmp_path, capsys):
    for i in range(2):
        store = TraceStore(tmp_path / f"s{i}")
        rec = Recorder(f"run {i}", save=False)
        rec.tool("search", {"q": str(i)}, result="hit")
        rec.respond("done", success=True)
        store.save(rec.trace)
    args = argparse.Namespace(store=str(tmp_path / "s0"), since=None,
                              digest_dir=None, json=False,
                              watch=False, interval=30.0, frames=None)
    assert cmd_status(args) == 0
    assert "worst tool:" not in capsys.readouterr().out
