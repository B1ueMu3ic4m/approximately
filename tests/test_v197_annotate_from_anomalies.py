"""v197: `annotate --from-anomalies` — triage starts itself.

Fleet anomalies name the traces; a human names the verdicts. This
command drafts one note per top anomaly (evidence inline, author
`approximately`, verdict left empty) for every trace that has no
notes yet — traces a human already touched are never re-drafted.
"""

import argparse
import json

from approximately.cli import cmd_annotate
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
    return store, slow.trace.id


def _args(store_dir, count=5, json_mode=True):
    return argparse.Namespace(store=store_dir, trace=None, note=None,
                              author="", verdict="",
                              from_anomalies=True,
                              anomaly_count=count, json=json_mode)


def test_drafts_note_for_the_anomalous_trace(tmp_path):
    store, slow_id = _seed(tmp_path / "s")
    assert cmd_annotate(_args(str(store.directory))) == 0
    entries = store.annotations(slow_id)
    assert len(entries) == 1
    assert entries[0]["author"] == "approximately"
    assert entries[0]["verdict"] == ""  # human names the verdict
    assert "search 30000ms" in entries[0]["note"]


def test_traces_with_notes_are_not_redrafted(tmp_path):
    store, slow_id = _seed(tmp_path / "s")
    assert cmd_annotate(_args(str(store.directory))) == 0
    assert cmd_annotate(_args(str(store.directory))) == 0
    assert len(store.annotations(slow_id)) == 1


def test_json_payload(tmp_path, capsys):
    store, _ = _seed(tmp_path / "s")
    assert cmd_annotate(_args(str(store.directory))) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"drafted": 1, "fleet_anomalies": 1}


def test_anomaly_count_caps_drafts(tmp_path):
    store = TraceStore(tmp_path / "s")
    for i, ms in enumerate((100, 150, 200, 250, 300,
                            50000, 50000, 50000, 50000)):
        rec = Recorder(f"run {i}", save=False)
        rec.tool("deploy", {"i": i}, result="ok")
        rec.respond("done", success=True)
        rec.trace.steps[0].latency_ms = ms
        store.save(rec.trace)
    assert cmd_annotate(_args(str(store.directory), count=2)) == 0
    assert len(store.annotations()) == 2
