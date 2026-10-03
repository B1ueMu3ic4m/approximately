"""Night VI, round 13: fuzz 21 — evidence, diff, cluster under
degenerate and hostile input.

The probes found no holes; these pins keep it that way.  Keyed-pack
verdict semantics (right key intact / wrong key wrong-key / no key
keyed), tamper detection, zero-step traces through packs and
scorecards, fifty identical failures collapsing to one cluster.
"""

import dataclasses
import zipfile

from approximately.cluster import agent_scorecard, cluster, store_stats, tool_scorecard, trend
from approximately.diff import diff as trace_diff
from approximately.evidence import build_evidence_pack, verify_evidence_pack
from approximately.integrity import sign
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store(tmp_path):
    store = TraceStore(tmp_path / "s")
    return store


def _record(store, task, tokens=10, fail=False, steps=1, tool="t"):
    with Recorder(task, model="m/1", store=store, save=False) as rec:
        for i in range(steps):
            rec.tool(tool, {"i": i}, tokens=tokens)
        rec.respond("done", success=not fail)
    store.save(rec.trace)
    return rec.trace


def _pack(store, trace_id, key=None, path=None):
    out = path or (store.directory.parent / f"{trace_id}.zip")
    build_evidence_pack(store, trace_id, out, key=key)
    return out


def test_keyed_pack_verdict_semantics(tmp_path):
    store = _store(tmp_path)
    trace = _record(store, "keyed run")
    sign(trace, key=b"k1")
    store.save(trace)
    pack = _pack(store, trace.id, key=b"k1")
    assert verify_evidence_pack(pack, key=b"k1")["chain"]["verdict"] \
        == "intact"
    assert verify_evidence_pack(pack, key=b"zzz")["chain"]["verdict"] \
        == "wrong-key"
    # keyed evidence without the key at hand is sealed, not broken
    no_key = verify_evidence_pack(pack)
    assert no_key["chain"]["verdict"] == "keyed"
    assert no_key["chain"]["intact"] is False


def test_zero_step_trace_packs_and_verifies(tmp_path):
    store = _store(tmp_path)
    trace = _record(store, "empty run", steps=0)
    pack = _pack(store, trace.id)
    verdict = verify_evidence_pack(pack)
    assert verdict["manifest_ok"] is True
    assert verdict["chain"]["intact"] is True


def test_tampered_member_is_named(tmp_path):
    store = _store(tmp_path)
    trace = _record(store, "victim")
    pack = _pack(store, trace.id)
    with zipfile.ZipFile(pack) as zf:
        data = {n: zf.read(n) for n in zf.namelist()}
    data["trace.json"] = data["trace.json"].replace(
        b"victim", b"HACKED")
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        for name, blob in data.items():
            zf.writestr(name, blob)
    verdict = verify_evidence_pack(bad)
    assert verdict["mismatched"] == ["trace.json"]
    assert verdict["manifest_ok"] is False


def test_missing_member_is_named(tmp_path):
    store = _store(tmp_path)
    trace = _record(store, "robbed")
    pack = _pack(store, trace.id)
    with zipfile.ZipFile(pack) as zf:
        data = {n: zf.read(n) for n in zf.namelist()
                if n != "annotations.json"}
    robbed = tmp_path / "robbed.zip"
    with zipfile.ZipFile(robbed, "w") as zf:
        for name, blob in data.items():
            zf.writestr(name, blob)
    verdict = verify_evidence_pack(robbed)
    assert verdict["missing"] == ["annotations.json"]
    assert verdict["manifest_ok"] is False


def test_fifty_identical_failures_make_one_cluster(tmp_path):
    store = _store(tmp_path)
    traces = [_record(store, f"same {i}", fail=True, tool="same")
              for i in range(50)]
    report = cluster(traces)
    assert len(report.clusters) == 1
    assert report.clusters[0].size == 50


def test_degenerate_traces_through_the_scorecards(tmp_path):
    store = _store(tmp_path)
    traces = [_record(store, f"empty {i}", steps=0) for i in range(4)]
    traces += [_record(store, "one real", steps=1)]
    assert store_stats(traces).traces == 5
    tool_scorecard(traces)
    agent_scorecard(traces)
    trend(traces)


def test_self_diff_is_stable(tmp_path):

    store = _store(tmp_path)
    trace = _record(store, "mirror", steps=2)
    left = trace_diff(trace, trace)
    right = trace_diff(trace, trace)
    assert dataclasses.asdict(left) == dataclasses.asdict(right)
    assert left.similarity == 1.0


def test_diff_of_zero_step_vs_normal(tmp_path):
    store = _store(tmp_path)
    empty = _record(store, "empty", steps=0)
    full = _record(store, "full", steps=3)
    result = trace_diff(empty, full)
    assert result.a_id == empty.id
    assert result.b_id == full.id
    assert result.counts  # structured, no crash
