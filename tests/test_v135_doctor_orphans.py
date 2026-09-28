"""v135: doctor finds orphan annotations.

After an import/clean/rotate cycle, annotation sidecars can reference
traces that no longer exist in the store. Doctor now names them so
triage knows which notes point at nothing — read-only diagnosis, as
always; nothing is removed automatically.
"""

import json

from approximately.doctor import doctor
from approximately.recorder import Recorder
from approximately.store import TraceStore


def test_orphan_annotations_reported(tmp_path):
    store = TraceStore(tmp_path / "s")
    rec = Recorder("keep me", save=False)
    rec.respond("done", success=True)
    store.save(rec.trace)
    gone = Recorder("delete me", save=False)
    gone.respond("done", success=True)
    store.save(gone.trace)
    store.annotate(gone.trace.id, "note on a trace about to vanish",
                   verdict="confirmed")
    # remove the trace out from under the sidecar
    (store.directory / f"{gone.trace.id}.json").unlink()

    report = doctor(store.directory)
    assert report.annotation_lines == 1
    assert report.annotation_orphans == [gone.trace.id]

    prose = report.render()
    assert "reference missing trace(s)" in prose
    assert f"orphan annotation: trace {gone.trace.id}" in prose


def test_attached_annotations_are_not_orphans(tmp_path):
    store = TraceStore(tmp_path / "s")
    rec = Recorder("stay", save=False)
    rec.respond("done", success=True)
    store.save(rec.trace)
    store.annotate(rec.trace.id, "attached", verdict="confirmed")
    report = doctor(store.directory)
    assert report.annotation_lines == 1
    assert report.annotation_orphans == []


def test_orphan_survives_corrupt_sibling_lines(tmp_path):
    store = TraceStore(tmp_path / "s")
    rec = Recorder("t", save=False)
    rec.respond("done", success=True)
    store.save(rec.trace)
    (store.directory / f"{rec.trace.id}.json").unlink()
    sidecar = store.directory / "annotations.jsonl"
    sidecar.write_text(
        json.dumps({"trace_id": rec.trace.id, "note": "x",
                    "verdict": "confirmed"}) + "\n"
        + "{broken json\n",
        encoding="utf-8")
    report = doctor(store.directory)
    assert report.annotation_orphans == [rec.trace.id]
    assert report.annotation_corrupt == 1
