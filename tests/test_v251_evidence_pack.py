"""v251: `approximately evidence` — the complete case, one archive.

A reviewer judging a run should not need the store, the tool, or
even this repo's docs: the pack carries the native record (integrity
chain embedded), the HTML postmortem, the trace's annotations, an
on-the-spot chain verdict, and a manifest that names the sha256 of
every member — the pack itself is tamper-evident.  Unknown ids are
a loud error; keyed chains verify with --key-file.
"""

import hashlib
import json
import zipfile

import pytest

from approximately.cli import main
from approximately.evidence import build_evidence_pack, verify_evidence_pack
from approximately.integrity import sign
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed(path):
    store = TraceStore(path)
    rec = Recorder("book a flight", model="gpt-x", store=store,
                   save=False)
    rec.tool("search", {"q": "SFO-NRT"}, tokens=800, latency_ms=620)
    rec.respond("booked", success=False)
    sign(rec.trace)
    store.save(rec.trace)
    store.annotate(rec.trace.id, "infra timeout",
                   verdict="confirmed", author="oncall")
    return store


def test_pack_carries_the_complete_case(tmp_path):
    store = _seed(tmp_path / "s")
    out = tmp_path / "case.zip"
    manifest = build_evidence_pack(store, rec_id(store), out)
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
    assert names == {"trace.json", "report.html", "annotations.json",
                     "brief.md", "manifest.json"}
    assert manifest["chain"]["intact"] is True
    assert manifest["verdict"] != ""
    assert manifest["members"]["trace.json"]
    # annotations rode along
    with zipfile.ZipFile(out) as zf:
        notes = json.loads(zf.read("annotations.json"))
    assert notes[0]["note"] == "infra timeout"


def rec_id(store):
    return store.list_traces()[0].id


def test_manifest_hashes_are_recomputable(tmp_path):
    store = _seed(tmp_path / "s")
    out = tmp_path / "case.zip"
    manifest = build_evidence_pack(store, rec_id(store), out)
    with zipfile.ZipFile(out) as zf:
        for name, digest in manifest["members"].items():
            assert hashlib.sha256(zf.read(name)).hexdigest() == digest


def test_unknown_trace_is_a_loud_error(tmp_path):
    store = TraceStore(tmp_path / "s")
    with pytest.raises(ValueError):
        build_evidence_pack(store, "nope", tmp_path / "x.zip")
    code = main(["evidence", "--store", str(tmp_path / "s"),
                 "nope", str(tmp_path / "x.zip")])
    assert code == 2


def test_keyed_chain_verifies_with_key_file(tmp_path):
    store = TraceStore(tmp_path / "s")
    key_file = tmp_path / "key.hex"
    key_file.write_text("ab" * 32, encoding="utf-8")
    from approximately.integrity import load_key, sign

    rec = Recorder("locked run", store=store, save=False)
    rec.respond("done", success=True)
    sign(rec.trace, key=load_key(str(key_file)))
    store.save(rec.trace)
    out = tmp_path / "case.zip"
    manifest = build_evidence_pack(store, rec_id(store), out,
                                   key=load_key(str(key_file)))
    assert manifest["chain"]["intact"] is True
    assert manifest["chain"]["verdict"] == "intact"


def test_cli_human_output_names_the_chain(tmp_path, capsys):
    store = _seed(tmp_path / "s")
    out = tmp_path / "case.zip"
    code = main(["evidence", "--store", str(store.directory),
                 rec_id(store), str(out)])
    assert code == 0
    text = capsys.readouterr().out
    assert "chain: intact" in text
    assert "trace.json:" in text


def test_store_archive_packs_every_trace(tmp_path):
    from approximately.evidence import build_store_packs

    store = _seed(tmp_path / "s")
    rec2 = Recorder("second run", store=store, save=False)
    rec2.respond("done", success=True)
    store.save(rec2.trace)
    out = tmp_path / "archive"
    report = build_store_packs(store, out)
    assert report["packs"] == 2
    zips = sorted(out.glob("*.evidence.zip"))
    assert len(zips) == 2
    index = json.loads((out / "index.json").read_text(
        encoding="utf-8"))
    assert index["packs"] == 2
    for row in index["traces"]:
        pack = out / row["pack"]
        assert hashlib.sha256(pack.read_bytes()).hexdigest() == \
            row["sha256"]


def test_store_archive_refuses_an_empty_store(tmp_path):
    from approximately.evidence import build_store_packs

    TraceStore(tmp_path / "s")
    with pytest.raises(ValueError):
        build_store_packs(TraceStore(tmp_path / "s"), tmp_path / "a")
    code = main(["evidence", "--store", str(tmp_path / "s"),
                 "--all", str(tmp_path / "a")])
    assert code == 2


def test_verify_accepts_an_honest_pack(tmp_path):
    from approximately.evidence import verify_evidence_pack

    store = _seed(tmp_path / "s")
    out = tmp_path / "case.zip"
    build_evidence_pack(store, rec_id(store), out)
    verdict = verify_evidence_pack(out)
    assert verdict["manifest_ok"] is True
    assert verdict["chain"]["intact"] is True
    code = main(["evidence", "--store", str(tmp_path / "s"),
                 "--verify", str(out)])
    assert code == 0


def test_verify_refuses_a_swapped_member(tmp_path):
    import zipfile

    from approximately.evidence import build_evidence_pack, verify_evidence_pack

    store = _seed(tmp_path / "s")
    out = tmp_path / "case.zip"
    build_evidence_pack(store, rec_id(store), out)
    # tamper: rewrite report.html, keep the old manifest
    with zipfile.ZipFile(out) as zf:
        members = {n: zf.read(n) for n in zf.namelist()}
    members["report.html"] = b"<html>forged</html>"
    with zipfile.ZipFile(out, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    verdict = verify_evidence_pack(out)
    assert verdict["manifest_ok"] is False
    assert "report.html" in verdict["mismatched"]
    assert verdict["chain"]["intact"] is True   # chain untouched
    code = main(["evidence", "--store", str(tmp_path / "s"),
                 "--verify", str(out)])
    assert code == 1


def test_verify_refuses_a_rewritten_record(tmp_path):
    # the deeper forgery: swap the record itself — the manifest
    # still matches the (re-hashed) members?  No: the manifest is
    # a member too, so ANY rewrite without re-signing the manifest
    # fails the hash check first
    import zipfile

    from approximately.evidence import build_evidence_pack, verify_evidence_pack

    store = _seed(tmp_path / "s")
    out = tmp_path / "case.zip"
    build_evidence_pack(store, rec_id(store), out)
    with zipfile.ZipFile(out) as zf:
        members = {n: zf.read(n) for n in zf.namelist()}
    record = json.loads(members["trace.json"])
    record["task"] = "rewritten after packing"
    members["trace.json"] = json.dumps(record).encode("utf-8")
    with zipfile.ZipFile(out, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    verdict = verify_evidence_pack(out)
    assert verdict["manifest_ok"] is False


def test_verify_rejects_a_non_pack(tmp_path):
    junk = tmp_path / "junk.zip"
    import zipfile as zfmod

    with zfmod.ZipFile(junk, "w") as zf:
        zf.writestr("readme.txt", "not an evidence pack")
    with pytest.raises(ValueError):
        verify_evidence_pack(junk)
