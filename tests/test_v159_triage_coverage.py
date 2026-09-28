"""v159: the glance knows how much triage is left.

`status` counts annotations; now it also answers "of the failures on
file, how many has anyone actually looked at" — annotated failures
over total failures, in the payload and as a prose line whenever the
ratio is below 100%.
"""

import argparse

from approximately.cli import _status_payload, cmd_status
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed(directory, failures=2, annotate=1):
    store = TraceStore(directory)
    ids = []
    for i in range(failures + 1):
        rec = Recorder(f"run {i}", save=False)
        if i < failures:
            rec.tool("deploy", {"env": "prod"}, result=None,
                     error="timeout")
            rec.respond("gave up", success=False)
        else:
            rec.respond("done", success=True)
        store.save(rec.trace)
        ids.append(rec.trace.id)
    for i in range(annotate):
        store.annotate(ids[i], "looked at it", verdict="confirmed")
    return store


def test_partial_coverage_in_payload(tmp_path):
    store = _seed(tmp_path / "s", failures=2, annotate=1)
    payload = _status_payload(store, store.list_traces(), None, None)
    cov = payload["triage_coverage"]
    assert cov == {"annotated_failures": 1, "failures": 2,
                   "ratio": 0.5}


def test_full_coverage_is_one(tmp_path):
    store = _seed(tmp_path / "s", failures=2, annotate=2)
    payload = _status_payload(store, store.list_traces(), None, None)
    assert payload["triage_coverage"]["ratio"] == 1.0


def test_no_failures_is_none_not_zero(tmp_path):
    store = TraceStore(tmp_path / "s")
    rec = Recorder("calm", save=False)
    rec.respond("done", success=True)
    store.save(rec.trace)
    payload = _status_payload(store, store.list_traces(), None, None)
    assert payload["triage_coverage"]["ratio"] is None


def test_prose_line_only_when_incomplete(tmp_path, capsys):
    store = _seed(tmp_path / "s", failures=2, annotate=1)
    args = argparse.Namespace(store=str(store.directory), since=None,
                              digest_dir=None, json=False,
                              watch=False, interval=30.0, frames=None)
    assert cmd_status(args) == 0
    assert "triage coverage: 1/2 failures annotated (50%)" in \
        capsys.readouterr().out
