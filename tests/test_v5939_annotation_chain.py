"""v5939: the triage log is evidence too — it gets a chain.

Annotations drive triage: a flipped verdict (``confirmed`` →
``false-positive``) silently rewrites the postmortem history, and
until now the sidecar was unsigned JSONL while the records
themselves carried a tamper-evident chain. Each new annotation
extends the previous stamp (keyed HMAC when a signing key is in
play, plain sha256 — tamper-EVIDENT — when not), so an edited
verdict or a removed line breaks every later link, named by line
and trace. ``doctor --deep`` walks the chain and a broken link
fails the health verdict. The contract stays honest about what it
can know: a legacy unsigned log verifies trivially (signed=0,
never broken), a corrupt line starts a fresh segment (exactly as
the writer's tail read would link it), and a keyed entry whose
key has rotated is UNVERIFIABLE — the content check needs the
key, but the link continuity never does.
"""

import json

import pytest

from approximately.recorder import Recorder
from approximately.store import TraceStore


@pytest.fixture
def store(tmp_path):
    store = TraceStore(tmp_path / "s")
    rec = Recorder("chain target run", save=False)
    rec.tool("deploy", {}, result=None, error="boom")
    rec.respond("done", success=False)
    store.save(rec.trace)
    return store, rec.trace.id


def test_annotations_chain_and_verify_intact(store):
    s, tid = store
    s.annotate(tid, "first look", verdict="confirmed")
    s.annotate(tid, "second look", verdict="confirmed")
    r = s.verify_annotations()
    assert (r["total"], r["signed"], r["unsigned"]) == (2, 2, 0)
    assert r["broken"] == []
    entry = json.loads((s.directory / "annotations.jsonl")
                       .read_text(encoding="utf-8")
                       .splitlines()[0])
    assert entry["alg"] == "sha256-chain-v2"
    assert entry["prev"] == "", \
        "the first signed entry chains from empty"


def test_an_edited_verdict_is_named(store):
    s, tid = store
    s.annotate(tid, "first look", verdict="confirmed")
    path = s.directory / "annotations.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[0])
    entry["verdict"] = "false-positive"
    lines[0] = json.dumps(entry)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    r = s.verify_annotations()
    assert len(r["broken"]) == 1, r
    assert "line 1" in r["broken"][0]
    assert tid in r["broken"][0], \
        "the tampered entry names its trace"


def test_a_removed_line_breaks_the_next_link(store):
    s, tid = store
    s.annotate(tid, "first look", verdict="confirmed")
    s.annotate(tid, "second look", verdict="confirmed")
    path = s.directory / "annotations.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text(lines[1] + "\n", encoding="utf-8")
    r = s.verify_annotations()
    assert r["broken"], \
        "the survivor's link points at a stamp that is gone"


def test_a_legacy_log_never_reads_as_broken(store):
    s, tid = store
    legacy = {"ts": 1.0, "trace_id": tid, "author": "analyst",
              "verdict": "confirmed", "note": "written before "
              "the chain existed"}
    (s.directory / "annotations.jsonl").write_text(
        json.dumps(legacy) + "\n", encoding="utf-8")
    r = s.verify_annotations()
    assert (r["total"], r["signed"], r["unsigned"]) == (1, 0, 1)
    assert r["broken"] == []
    s.annotate(tid, "appended after the upgrade",
               verdict="confirmed")
    r2 = s.verify_annotations()
    assert r2["signed"] == 1 and r2["broken"] == [], \
        "signed entries append cleanly after a legacy tail"


def test_a_keyed_entry_rotated_out_is_unverifiable_not_broken(
        store, monkeypatch):
    s, tid = store
    monkeypatch.setenv("APPROXIMATELY_SIGNING_KEY", "night-key")
    s.annotate(tid, "keyed note", verdict="confirmed")
    entry = json.loads((s.directory / "annotations.jsonl")
                       .read_text(encoding="utf-8")
                       .splitlines()[0])
    assert entry["alg"] == "hmac-sha256-chain-v2"
    assert entry.get("key_id"), "the keyed entry names its key"
    monkeypatch.delenv("APPROXIMATELY_SIGNING_KEY")
    r = s.verify_annotations()
    assert r["unverifiable"] == 1 and r["broken"] == [], \
        "no key means cannot judge, not tampered"
    monkeypatch.setenv("APPROXIMATELY_SIGNING_KEY", "night-key")
    r2 = s.verify_annotations()
    assert r2["unverifiable"] == 0 and r2["broken"] == []
    monkeypatch.setenv("APPROXIMATELY_SIGNING_KEY", "other-key")
    r3 = s.verify_annotations()
    assert r3["broken"], "the wrong key must not bless the entry"


def test_doctor_deep_verdicts_on_the_chain(store):
    from approximately.doctor import doctor

    s, tid = store
    s.annotate(tid, "looks like FM-1.3", verdict="confirmed")
    report = doctor(s.directory, deep=True)
    assert report.annotation_signed == 1 and report.healthy
    assert "annotation chain: 1 signed" in report.render()
    path = s.directory / "annotations.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[0])
    entry["note"] = "quietly different"
    lines[0] = json.dumps(entry)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tampered = doctor(s.directory, deep=True)
    assert tampered.annotation_broken and not tampered.healthy, \
        "verdicts drive triage: a broken chain is broken evidence"
    assert "BROKEN" in tampered.render()
    payload = tampered.to_dict()
    assert payload["annotation_broken"]
    shallow = doctor(s.directory)
    assert shallow.annotation_signed == 0, (
        "the chain walk is a deep pass; the shallow door stays "
        "cheap")
