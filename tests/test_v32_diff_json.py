"""v0.32: diff --json and per-entry similarity ranking.

The NW edit script (v0.6) gains a char-similarity score on every
differing entry and a machine-readable output, so CI can rank "which
mutated step diverged most" instead of eyeballing previews.
"""

from __future__ import annotations

import json

from approximately.cli import cmd_diff
from approximately.diff import Op, diff
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _trace(tmp_path, tid: str, steps):
    """steps: (args, result) pairs — args shape drives alignment."""
    rec = Recorder("run the pipeline", save=False)
    rec.trace.id = tid
    for args, text in steps:
        rec.tool("assistant", args, result=text)
    rec.respond("done", success=True)
    store = TraceStore(str(tmp_path))
    store.save(rec.trace)
    return rec.trace


def _s(path_arg, text):
    return ({"path": path_arg}, text)


class TestDiffSimilarity:
    def test_mutated_entry_carries_char_similarity(self, tmp_path):
        a = _trace(tmp_path, "d-a", [_s("a.py", "run tests suite alpha"),
                                     _s("b", "deploy to staging")])
        b = _trace(tmp_path, "d-b", [_s("b.py", "run tests suite beta"),
                                     _s("b", "deploy to staging")])
        result = diff(a, b)
        mutated = [e for e in result.entries if e.op == Op.MUTATED]
        assert len(mutated) == 1
        assert 0.0 < mutated[0].similarity < 1.0

    def test_identical_results_score_one(self, tmp_path):
        a = _trace(tmp_path, "d-a", [_s("a.py", "same work")])
        b = _trace(tmp_path, "d-b", [_s("a.py", "same work")])
        result = diff(a, b)
        assert all(e.similarity == 1.0 for e in result.entries)

    def test_gaps_score_zero(self, tmp_path):
        a = _trace(tmp_path, "d-a", [_s("a.py", "step one"),
                                     _s("b.py", "step two goes away")])
        b = _trace(tmp_path, "d-b", [_s("a.py", "step one")])
        result = diff(a, b)
        divergences = result.divergences()
        assert divergences and divergences[0].similarity == 0.0

    def test_divergences_rank_worst_first(self, tmp_path):
        a = _trace(tmp_path, "d-a", [_s("a.py", "totally different workload"),
                                     _s("b.py", "run tests suite alpha")])
        b = _trace(tmp_path, "d-b", [_s("b.py", "run tests suite beta"),
                                     _s("a.py", "utterly unrelated task")])
        result = diff(a, b)
        ranked = result.divergences()
        assert len(ranked) >= 2
        assert ranked[0].similarity <= ranked[-1].similarity


class TestCliJson:
    def test_json_counts_and_entries(self, tmp_path, capsys):
        _trace(tmp_path, "j-a", [_s("a.py", "run tests suite alpha"),
                                 _s("b", "deploy to staging")])
        _trace(tmp_path, "j-b", [_s("b.py", "run tests suite beta")])
        args = type("A", (), {"store": str(tmp_path),
                              "trace": "j-a", "other": "j-b",
                              "json": True})()
        assert cmd_diff(args) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["mutated"] == 1
        assert payload["deleted"] == 1
        assert payload["similarity"] < 1.0
        ops = {e["op"] for e in payload["entries"]}
        assert ops == {"~", "-"}
        for entry in payload["entries"]:
            assert "similarity" in entry

    def test_json_identical_traces(self, tmp_path, capsys):
        _trace(tmp_path, "j-a", [_s("a.py", "same"), _s("b", "same two")])
        _trace(tmp_path, "j-b", [_s("a.py", "same"), _s("b", "same two")])
        args = type("A", (), {"store": str(tmp_path),
                              "trace": "j-a", "other": "j-b",
                              "json": True})()
        assert cmd_diff(args) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["entries"] == []
        assert payload["similarity"] == 1.0

    def test_text_mode_unchanged(self, tmp_path, capsys):
        _trace(tmp_path, "j-a", [_s("a.py", "step one")])
        _trace(tmp_path, "j-b", [_s("a.py", "step one")])
        args = type("A", (), {"store": str(tmp_path),
                              "trace": "j-a", "other": "j-b",
                              "json": False})()
        assert cmd_diff(args) == 0
        assert "similarity" in capsys.readouterr().out
