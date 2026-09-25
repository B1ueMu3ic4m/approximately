"""v110: annotations hygiene — merge carries the sidecar, doctor reads it.

Notes about a run belong to the run: `merge` now transports the
annotation sidecar to the target store (re-anchored to renamed trace
ids, deduped, append order preserved), and `doctor` reports the
sidecar's line and unreadable-line tallies. A torn tail from a crash
is reported but does not flip `healthy` — notes are advisory, not
evidence.
"""


from approximately.doctor import doctor
from approximately.merge import merge_store
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store(tmp_path, name, tid="h-1"):
    store = TraceStore(str(tmp_path / name))
    rec = Recorder("hygiene fixture", save=False)
    rec.trace.id = tid
    rec.respond("done", success=True)
    store.save(rec.trace)
    return store


def test_merge_carries_annotations(tmp_path):
    source = _store(tmp_path, "src")
    target = _store(tmp_path, "dst", tid="h-2")
    source.annotate("h-1", "infra timeout", author="oncall",
                    verdict="confirmed")
    report = merge_store(source.directory, target)
    assert report.imported == ["h-1"]
    assert report.annotations_carried == 1
    rows = target.annotations("h-1")
    assert rows[0]["note"] == "infra timeout"
    assert rows[0]["verdict"] == "confirmed"


def test_merge_renames_reanchor_annotations(tmp_path):
    source = _store(tmp_path, "src")
    target = _store(tmp_path, "dst")
    target.save(_store(tmp_path, "src").load("h-1"))  # force the conflict
    source.annotate("h-1", "note before rename")
    report = merge_store(source.directory, target, on_conflict="rename")
    new_id = report.renamed["h-1"]
    assert report.annotations_carried == 1
    rows = target.annotations(new_id)
    assert rows[0]["note"] == "note before rename"
    assert target.annotations("h-1") == []


def test_merge_does_not_duplicate_notes(tmp_path):
    source = _store(tmp_path, "src")
    target = _store(tmp_path, "dst", tid="h-2")
    source.annotate("h-1", "already there")
    report = merge_store(source.directory, target)
    report2 = merge_store(source.directory, target)  # re-merge: skip path
    assert report.annotations_carried == 1
    assert report2.annotations_carried == 0
    assert len(target.annotations("h-1")) == 1


def test_doctor_counts_sidecar_lines(tmp_path):
    store = _store(tmp_path, "s")
    store.annotate("h-1", "one")
    store.annotate("h-1", "two")
    report = doctor(store.directory)
    assert report.annotation_lines == 2
    assert report.annotation_corrupt == 0
    rendered = report.render()
    assert "annotations: 2 note(s)" in rendered
    assert report.healthy is True


def test_doctor_reports_corrupt_lines(tmp_path):
    store = _store(tmp_path, "s")
    store.annotate("h-1", "valid")
    path = store.directory / "annotations.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"trace_id": "h-1", "note": "torn')
        fh.write("\nnot json\n")
    report = doctor(store.directory)
    assert report.annotation_lines == 3
    assert report.annotation_corrupt == 2
    assert "2 unreadable line(s)" in report.render()
    # advisory: torn notes do not fail the CI verdict
    assert report.healthy is True


def test_doctor_absent_sidecar_is_silent(tmp_path):
    store = _store(tmp_path, "s")
    report = doctor(store.directory)
    assert report.annotation_lines == 0
    assert "annotations:" not in report.render()
