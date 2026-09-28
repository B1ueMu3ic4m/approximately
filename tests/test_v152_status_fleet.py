"""v152: the ops glance knows when the fleet is misbehaving.

`status` already answers "are we failing, what hurts, who keeps
failing". Now it also answers "is anything *slow* in a way the store
never sees": the payload carries `fleet_anomalies` (count + the worst
offender with its tool, latency, family median and z), and the prose
render adds a fleet-anomalies line when the count is nonzero.
"""

import argparse

from approximately.cli import _status_payload, cmd_status
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed(directory):
    store = TraceStore(directory)
    jitter = (1800, 2000, 2100, 1900)
    for i in range(4):
        rec = Recorder(f"boring {i}", save=False)
        rec.tool("search", {"q": str(i)}, result="hit")
        rec.respond("done", success=True)
        rec.trace.steps[0].latency_ms = jitter[i]
        store.save(rec.trace)
    slow = Recorder("the slow one", save=False)
    slow.tool("search", {"q": "heavy"}, result="hit")
    slow.respond("done", success=True)
    slow.trace.steps[0].latency_ms = 30000
    store.save(slow.trace)
    return store


def test_status_payload_carries_fleet_anomalies(tmp_path):
    store = _seed(tmp_path / "s")
    payload = _status_payload(store, store.list_traces(), None, None)
    fleet = payload["fleet_anomalies"]
    assert fleet["count"] == 1
    assert fleet["worst"]["tool"] == "search"
    assert fleet["worst"]["latency_ms"] == 30000


def test_quiet_fleet_reports_zero(tmp_path):
    store = TraceStore(tmp_path / "s")
    rec = Recorder("calm", save=False)
    rec.respond("done", success=True)
    store.save(rec.trace)
    payload = _status_payload(store, store.list_traces(), None, None)
    assert payload["fleet_anomalies"]["count"] == 0
    assert payload["fleet_anomalies"]["worst"] is None


def test_prose_render_names_the_offender(tmp_path, capsys):
    _seed(tmp_path / "s")
    args = argparse.Namespace(store=str(tmp_path / "s"), since=None,
                              digest_dir=None, json=False,
                              watch=False, interval=30.0, frames=None)
    assert cmd_status(args) == 0
    out = capsys.readouterr().out
    assert "fleet anomalies: 1" in out
    assert "search 30000ms" in out
