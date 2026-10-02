"""v255: fuzz round 19 — the compare and evidence doors.

Round contract unchanged: documented errors or clean skips, never
a crash.  This round's predictable gap, closed before it shipped:
`compare` over an empty store now refuses loudly (the v230
contract — a comparison against nothing proves nothing), on either
side.  The evidence door survives a trace with junk annotations
and a hostile meta; a huge postmortem still packs.
"""

import json
import zipfile

import pytest

from approximately.cli import main
from approximately.evidence import build_evidence_pack
from approximately.recorder import Recorder
from approximately.store import TraceStore


def test_compare_refuses_empty_baseline(tmp_path, capsys):
    TraceStore(tmp_path / "a")
    _seed_one(tmp_path / "b")
    code = main(["compare", "--baseline", str(tmp_path / "a"),
                 "--candidate", str(tmp_path / "b")])
    assert code == 2
    assert "empty" in capsys.readouterr().err


def test_compare_refuses_empty_candidate(tmp_path, capsys):
    _seed_one(tmp_path / "a")
    TraceStore(tmp_path / "b")
    code = main(["compare", "--baseline", str(tmp_path / "a"),
                 "--candidate", str(tmp_path / "b")])
    assert code == 2
    assert "empty" in capsys.readouterr().err


def _seed_one(path):
    store = TraceStore(path)
    rec = Recorder("run", save=False)
    rec.respond("done", success=True)
    store.save(rec.trace)
    return store


def test_evidence_survives_junk_annotations(tmp_path):
    store = _seed_one(tmp_path / "s")
    # an annotation line that is not even an object: the pack must
    # carry what is readable, not crash on the rest
    store.annotate(store.list_traces()[0].id, "real note")
    annotations = store.directory / "annotations.jsonl"
    lines = annotations.read_text(encoding="utf-8").splitlines()
    lines.append('"just a string, not a dict"')
    annotations.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = tmp_path / "case.zip"
    manifest = build_evidence_pack(store, store.list_traces()[0].id,
                                   out)
    with zipfile.ZipFile(out) as zf:
        notes = json.loads(zf.read("annotations.json"))
    assert isinstance(notes, list)


def test_evidence_survives_non_dict_meta(tmp_path):
    store = TraceStore(tmp_path / "s")
    trace = _seed_one(tmp_path / "x").list_traces()[0]
    trace.meta = "junk"
    store.save(trace, stamp=False)
    out = tmp_path / "case.zip"
    manifest = build_evidence_pack(store, trace.id, out)
    assert manifest["chain"]["signed"] is False


def test_evidence_packs_a_big_postmortem(tmp_path):
    store = TraceStore(tmp_path / "s")
    rec = Recorder("wide run", store=store, save=False)
    for i in range(2_000):
        rec.tool("probe", {"i": i}, result="x" * 200)
    rec.respond("done", success=False)
    store.save(rec.trace)
    out = tmp_path / "big.zip"
    build_evidence_pack(store, rec.trace.id, out)
    assert out.stat().st_size > 10_000
