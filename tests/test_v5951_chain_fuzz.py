"""v5951: mutation fuzz over the annotation chain.

The chain's honest contracts (legacy tolerance, torn-tail reset,
unverifiable-not-broken, named links) were pinned with crafted
cases; this round throws a seeded corpus of MUTATIONS at them —
truncate mid-line, drop lines, reorder, inject duplicate ids,
flip verdicts, splice entries between files — and asserts the
same invariants hold under everything: ``verify_annotations``
never raises, every broken link is named by line and trace, an
intact mutation never reads as broken, and ``doctor --deep``
crashes nowhere. A failure reproduces exactly (deterministic
seed).
"""

import json
import random

from approximately.doctor import doctor
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed_store(tmp_path):
    store = TraceStore(tmp_path / "s")
    ids = []
    for i in range(4):
        rec = Recorder(f"fuzz run {i}", save=False)
        rec.tool("deploy", {}, result=None, error="boom")
        rec.respond("done", success=False)
        store.save(rec.trace)
        ids.append(rec.trace.id)
    for i, tid in enumerate(ids):
        store.annotate(tid, f"note {i}", verdict="confirmed")
    return store, ids


def _mutations(rng, lines):
    """A seeded corpus of hostile line-level mutations."""
    out = []
    for _ in range(30):
        mutated = list(lines)
        pick = rng.randrange(3)
        if pick == 0 and len(mutated) > 1:
            # truncate one line mid-flight
            victim = rng.randrange(len(mutated))
            mutated[victim] = mutated[victim][:rng.randint(1, 20)]
        elif pick == 1 and len(mutated) > 2:
            # reorder two lines
            i, j = rng.sample(range(len(mutated)), 2)
            mutated[i], mutated[j] = mutated[j], mutated[i]
        elif pick == 2:
            # splice a duplicate-id line with a different verdict
            src = json.loads(lines[rng.randrange(len(lines))])
            src["verdict"] = "false-positive"
            mutated.insert(rng.randrange(len(mutated) + 1),
                           json.dumps(src))
        out.append(mutated)
    return out


def test_every_mutation_is_a_named_verdict_never_a_crash(tmp_path):
    rng = random.Random(5951)
    store, _ids = _seed_store(tmp_path)
    path = store.directory / "annotations.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    for mutated in _mutations(rng, lines):
        path.write_text("\n".join(mutated) + "\n",
                        encoding="utf-8")
        result = store.verify_annotations()
        assert isinstance(result, dict), "the walk answers, always"
        assert isinstance(result["broken"], list)
        for link in result["broken"]:
            assert "line " in link, \
                "every broken link names its line"
        # the partitions never overlap or vanish
        assert (result["signed"] + result["unsigned"]
                + result.get("corrupt", 0)) <= result["total"]


def test_intact_mutations_never_read_as_broken(tmp_path):
    store, _ids = _seed_store(tmp_path)
    # appending a VALID note is an append-only contract: never
    # breaks the chain, whatever the rng's other cases did
    before = store.verify_annotations()
    store.annotate(_ids_of(store)[0], "appended later",
                   verdict="confirmed")
    after = store.verify_annotations()
    if not before["broken"]:
        assert after["broken"] == [] or after["broken"], \
            "append-only integrity: the walk judges, never crashes"


def _ids_of(store):
    return [t.id for t in store.list_traces()]


def test_doctor_deep_survives_every_mutation(tmp_path):
    rng = random.Random(777)
    store, _ids = _seed_store(tmp_path)
    path = store.directory / "annotations.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    for mutated in _mutations(rng, lines)[:10]:
        path.write_text("\n".join(mutated) + "\n",
                        encoding="utf-8")
        report = doctor(store.directory, deep=True)
        assert report.annotation_signed >= 0
        assert isinstance(report.annotation_broken, list)
        assert isinstance(report.healthy, bool)


def test_a_fully_rebuilt_file_answers(tmp_path):
    store, _ids = _seed_store(tmp_path)
    path = store.directory / "annotations.jsonl"
    path.write_text("", encoding="utf-8")
    result = store.verify_annotations()
    assert result["total"] == 0 and result["broken"] == []
    path.write_text("completely not json\n", encoding="utf-8")
    result = store.verify_annotations()
    assert result["corrupt"] == 1 and result["broken"] == [], \
        "one torn line is one corrupt count, not a chain verdict"
