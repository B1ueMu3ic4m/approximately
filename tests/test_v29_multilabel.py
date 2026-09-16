"""v0.29: multi-label evaluation — set-based P/R/F1, converter, CLI."""

from __future__ import annotations

import json

from approximately.distill import evaluate_multi
from approximately.mastdata import convert_mast
from approximately.recorder import Recorder


def _trace(name):
    rec = Recorder(name, save=False)
    rec.tool("work", {}, result="ok")
    rec.respond("done")
    return rec.trace


class TestEvaluateMulti:
    def test_perfect_set_prediction(self):
        # a trace whose rules genuinely fire FM-1.3, gold = {FM-1.3}
        rec = Recorder("loopy", save=False)
        for _ in range(6):
            rec.tool("scroll", {"n": 1}, result="same content")
        rec.respond("gave up", success=False)
        from approximately.detectors import run_rules

        predicted = {d.mode_id for d in run_rules(rec.trace)
                     if d.confidence >= 0.5}
        pairs = [(rec.trace, predicted)]  # gold := prediction: perfect by construction
        result = evaluate_multi(pairs)
        assert result.sample_precision == 1.0
        assert result.sample_recall == 1.0
        assert result.macro_f1 == 1.0

    def test_partial_overlap_scores_both_ways(self):
        # the rules fire FM-1.3; gold adds FM-2.1 -> precision 1, recall .5
        rec = Recorder("loopy", save=False)
        for _ in range(6):
            rec.tool("scroll", {"n": 1}, result="same content")
        rec.respond("gave up", success=False)
        pairs = [(rec.trace, {"FM-1.3", "FM-2.1"})]
        result = evaluate_multi(pairs)
        # repeat fires (predicted FM-1.3); gold has FM-1.3 + FM-2.1
        assert 0 < result.sample_precision <= 1
        assert 0 < result.sample_recall < 1

    def test_empty_prediction_counts_all_gold_as_fn(self):
        trace = _trace("a")
        pairs = [(trace, {"FM-2.2"})]
        result = evaluate_multi(pairs)
        assert result.per_mode["FM-2.2"]["fn"] == 1
        assert result.sample_recall == 0.0

    def test_no_samples(self):
        result = evaluate_multi([])
        assert result.macro_f1 == 0.0 and result.samples == 0

    def test_per_mode_counts_accumulate(self):
        t1, t2 = _trace("x"), _trace("y")
        pairs = [(t1, {"FM-2.2"}), (t2, {"FM-2.2", "FM-2.4"})]
        result = evaluate_multi(pairs)
        assert result.per_mode["FM-2.2"]["fn"] == 2


class TestConvertMultiLabel:
    def _record(self, options):
        return {
            "instance_id": "i-1",
            "problem_statement": ["Do it."],
            "other_data": {"correct": False},
            "trajectory": [
                {"role": "user", "content": ["go"]},
                *[{"role": "assistant", "content": [f"turn {i} proceeds"]}
                  for i in range(4)],
            ],
            "note": {"options": options},
        }

    def test_multi_label_emits_labels_set(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.json").write_text(json.dumps(self._record(
            {"Step repetition": "yes", "Trajectory restart": "yes"})))
        stats = convert_mast(src, tmp_path / "out.jsonl", multi_label=True)
        assert stats.converted == 1
        row = json.loads((tmp_path / "out.jsonl").read_text())
        assert sorted(row["labels"]) == ["FM-1.3", "FM-2.1"]

    def test_single_label_mode_still_excludes_multi(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.json").write_text(json.dumps(self._record(
            {"Step repetition": "yes", "Trajectory restart": "yes"})))
        stats = convert_mast(src, tmp_path / "out.jsonl")
        assert stats.excluded_multi_label == 1

    def test_end_to_end_benchmark(self, tmp_path, capsys):
        from approximately.cli import main

        src = tmp_path / "src"
        src.mkdir()
        (src / "a.json").write_text(json.dumps(self._record(
            {"Step repetition": "yes"})))
        bench = tmp_path / "multi.jsonl"
        rc = main(["convert-mast", str(src), str(bench), "--multi-label"])
        assert rc == 0
        rc = main(["--store", str(tmp_path / "st"), "benchmark",
                   str(bench), "--multi-label"])
        assert rc == 0
        assert "set-based" in capsys.readouterr().out
