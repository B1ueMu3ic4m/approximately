"""Night VI, round 6: quarantine for the unreadable.

A corrupt record file is re-reported on every scan, forever, and
nothing can act on it.  ``doctor --fix`` now moves those bytes into
``<store>/.quarantine/`` with a jsonl manifest (what, when, why) —
preserved for forensics, out of the store's hair.  Unlink stays
hygiene-only: quarantine never destroys evidence.
"""

import json

from approximately.cli import main
from approximately.doctor import QUARANTINE_DIR, doctor, quarantine_corrupt
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store_with_one_good(tmp_path):
    store = TraceStore(tmp_path)
    with Recorder("healthy run", model="m/1", store=store) as rec:
        rec.tool("t", tokens=10)
        rec.respond("done", success=True)
    return store


def test_doctor_reports_corrupt_then_fix_quarantines(tmp_path):
    _store_with_one_good(tmp_path)
    poison = tmp_path / "deadbeef.json"
    poison.write_text("{not json", encoding="utf-8")

    before = doctor(tmp_path)
    assert "deadbeef.json" in before.corrupt
    assert before.healthy is False
    assert before.corrupt_detail["deadbeef.json"].startswith(
        "JSONDecodeError")

    moved = quarantine_corrupt(tmp_path, before)
    assert moved == ["deadbeef.json"]
    quarantined = tmp_path / QUARANTINE_DIR / "deadbeef.json"
    assert quarantined.read_text(encoding="utf-8") == "{not json"
    lines = (tmp_path / QUARANTINE_DIR / "manifest.jsonl"
             ).read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[0])
    assert entry["file"] == "deadbeef.json"
    assert "JSONDecodeError" in entry["error"]
    assert isinstance(entry["moved_at"], float)

    after = doctor(tmp_path)
    assert after.corrupt == []
    assert after.healthy is True


def test_cli_fix_flag_runs_the_quarantine(tmp_path, capsys):
    _store_with_one_good(tmp_path)
    (tmp_path / "broken.json").write_text("[], not an object",
                                          encoding="utf-8")
    rc = main(["doctor", "--store", str(tmp_path), "--fix", "--json"])
    captured = capsys.readouterr()
    err, out = captured.err, captured.out
    assert rc == 0  # quarantined store is healthy again
    assert "quarantined 1 corrupt record(s)" in err
    payload = json.loads(out)
    assert payload["quarantined"] == ["broken.json"]
    assert payload["corrupt"] == []
    assert (tmp_path / QUARANTINE_DIR / "broken.json").is_file()


def test_name_clash_gets_suffixed_never_overwritten(tmp_path):
    _store_with_one_good(tmp_path)
    qdir = tmp_path / QUARANTINE_DIR
    qdir.mkdir()
    (qdir / "x.json").write_text("previous quarantine",
                                 encoding="utf-8")
    (tmp_path / "x.json").write_text("current poison",
                                     encoding="utf-8")
    report = doctor(tmp_path)
    moved = quarantine_corrupt(tmp_path, report)
    assert moved == ["x.json"]
    assert (qdir / "x.json").read_text() == "previous quarantine"
    assert (qdir / "x.json.1").read_text() == "current poison"


def test_vanished_file_is_skipped(tmp_path):
    report = doctor(tmp_path)
    report.corrupt = ["ghost.json"]
    assert quarantine_corrupt(tmp_path, report) == []
    assert not (tmp_path / QUARANTINE_DIR / "ghost.json").exists()


def test_no_corrupt_no_quarantine_dir(tmp_path):
    _store_with_one_good(tmp_path)
    report = doctor(tmp_path)
    assert quarantine_corrupt(tmp_path, report) == []
    assert not (tmp_path / QUARANTINE_DIR).exists()


def test_schema_poison_is_quarantined_too(tmp_path):
    # valid JSON, wrong shape: the AttributeError path in
    # _check_records
    _store_with_one_good(tmp_path)
    (tmp_path / "lies.json").write_text('{"steps": "not-a-list"}',
                                        encoding="utf-8")
    report = doctor(tmp_path)
    assert "lies.json" in report.corrupt
    moved = quarantine_corrupt(tmp_path, report)
    assert moved == ["lies.json"]
    entry = json.loads(
        (tmp_path / QUARANTINE_DIR / "manifest.jsonl")
        .read_text(encoding="utf-8").splitlines()[0])
    assert entry["error"]  # the reason travels with the file
