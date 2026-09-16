"""v0.11: cross-store merge — conflict policies, evidence refusal."""

from __future__ import annotations

import pytest

from approximately.integrity import sign
from approximately.merge import merge_store
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _make_store(path, tasks, signed=False):
    store = TraceStore(path)
    for task in tasks:
        rec = Recorder(task, store=store, save=False)
        rec.tool("search", {"q": task}, result="ok")
        rec.respond("done", success=True)
        if signed:
            sign(rec.trace)
        store.save(rec.trace)
    return store


@pytest.fixture()
def target(tmp_path):
    return _make_store(tmp_path / "target", ["existing task"])


class TestBasicMerge:
    def test_unsigned_import(self, tmp_path, target):
        _make_store(tmp_path / "src", ["team A task", "team B task"])
        report = merge_store(tmp_path / "src", target)
        assert report.imported and not report.refused_tampered
        assert len(target.list_traces()) == 3

    def test_signed_intact_import(self, tmp_path, target):
        _make_store(tmp_path / "src", ["signed task"], signed=True)
        report = merge_store(tmp_path / "src", target)
        assert len(report.imported) == 1
        loaded = target.load(report.imported[0])
        assert loaded.meta["integrity"]["final"]


class TestEvidenceRefusal:
    def test_tampered_trace_refused(self, tmp_path, target):
        src = _make_store(tmp_path / "src", ["honest"], signed=True)
        honest_id = src.list_traces()[0].id
        # a tampered sibling: same store, edited after signing
        rec = Recorder("forged", store=src, save=False)
        rec.tool("deploy", {}, result="all good")
        rec.respond("done", success=True)
        sign(rec.trace)
        rec.trace.steps[0].result = "edited after signing"
        src.save(rec.trace)

        report = merge_store(tmp_path / "src", target)
        assert honest_id in report.imported
        assert rec.trace.id in report.refused_tampered
        assert target.load(rec.trace.id) is None  # never imported

    def test_unsigned_and_keyed_import_but_not_forged(self, tmp_path, target):
        src = TraceStore(tmp_path / "src")
        rec = Recorder("locked", store=src, save=False)
        rec.respond("ok")
        sign(rec.trace, key=b"a-key" * 4)  # keyed; verifier has no key
        src.save(rec.trace)
        report = merge_store(tmp_path / "src", target)
        assert report.imported  # locked != broken


class TestConflictPolicies:
    def test_skip_keeps_target(self, tmp_path, target):
        original = target.list_traces()[0]
        _make_store(tmp_path / "src", ["existing task"])  # same task, new id?
        # force an id collision: save the target's trace into src too
        src = TraceStore(tmp_path / "src")
        src.save(original)
        report = merge_store(tmp_path / "src", target)
        assert report.skipped_conflicts == [original.id]
        assert target.load(original.id).task == original.task

    def test_replace_takes_source(self, tmp_path, target):
        original = target.list_traces()[0]
        clone = TraceStore(tmp_path / "src")
        imported = Recorder(original.task + " overwritten", save=False)
        imported.respond("new evidence")
        imported.trace.id = original.id
        clone.save(imported.trace)

        merge_store(tmp_path / "src", target, on_conflict="replace")
        assert target.load(original.id).task.endswith("overwritten")

    def test_rename_imports_both(self, tmp_path, target):
        original = target.list_traces()[0]
        clone = TraceStore(tmp_path / "src")
        twin = Recorder("twin run", save=False)
        twin.respond("ok")
        twin.trace.id = original.id
        clone.save(twin.trace)

        report = merge_store(tmp_path / "src", target, on_conflict="rename")
        assert report.renamed[original.id].startswith(original.id + "-m")
        assert target.load(original.id).task == original.task
        assert target.load(report.renamed[original.id]).task == "twin run"

    def test_rename_handles_repeated_collisions(self, tmp_path):
        target = _make_store(tmp_path / "t", ["base"])
        base_id = target.list_traces()[0].id
        src = TraceStore(tmp_path / "s")
        twin = Recorder("twin", save=False)
        twin.respond("ok")
        twin.trace.id = base_id
        src.save(twin.trace)

        # the same conflicting id merged three times: -m2, -m3, -m4
        new_ids = []
        for _ in range(3):
            report = merge_store(tmp_path / "s", target,
                                 on_conflict="rename")
            new_ids.extend(report.imported)
        assert len(new_ids) == 3
        assert len(set(new_ids)) == 3  # all unique


class TestGuards:
    def test_same_directory_refused(self, tmp_path):
        store = _make_store(tmp_path / "s", ["t"])
        with pytest.raises(ValueError, match="same directory"):
            merge_store(tmp_path / "s", store)

    def test_bad_policy_refused(self, tmp_path, target):
        with pytest.raises(ValueError, match="on_conflict"):
            merge_store(tmp_path / "src", target, on_conflict="overwrite")

    def test_summary_counts(self, tmp_path, target):
        _make_store(tmp_path / "src", ["fresh one"])
        original = target.list_traces()[0]
        clone = TraceStore(tmp_path / "src2")
        twin = Recorder("dup", save=False)
        twin.respond("ok")
        twin.trace.id = original.id
        clone.save(twin.trace)
        report = merge_store(tmp_path / "src", target)
        report2 = merge_store(tmp_path / "src2", target)
        assert "1 imported" in report.summary()
        assert "1 skipped" in report2.summary()
