"""v0.13: MAST-Data converter — honest multi-label and coverage rules."""

from __future__ import annotations

import json

from approximately.mastdata import OPTION_TO_MODE, convert_mast


def _record(options, trajectory=None, correct=False, instance="x-1"):
    return {
        "instance_id": instance,
        "problem_statement": ["Do the thing."],
        "other_data": {"correct": correct},
        "trajectory": trajectory or [
            {"role": "user", "name": "planner", "content": ["go"]},
            {"role": "assistant", "name": "worker",
             "content": ["step one", "step one"]},
            {"role": "assistant", "name": "worker",
             "content": ["step two proceeds"]},
            {"role": "assistant", "name": "worker",
             "content": ["step three proceeds further"]},
            {"role": "assistant", "name": "worker",
             "content": ["step four concludes the work"]},
        ],
        "note": {"text": ["..."], "options": options},
    }


class TestConversion:
    def test_single_label_converted(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.json").write_text(json.dumps(_record(
            {"Step repetition": "yes"})))
        stats = convert_mast(src, tmp_path / "out.jsonl")
        assert stats.converted == 1
        row = json.loads((tmp_path / "out.jsonl").read_text().splitlines()[0])
        assert row["label"] == "FM-1.3"
        assert row["success"] is False
        assert any(s["kind"] == "tool_call" for s in row["steps"])

    def test_content_list_joined(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.json").write_text(json.dumps(_record(
            {"Derailing from task objectives": "yes"})))
        convert_mast(src, tmp_path / "out.jsonl")
        row = json.loads((tmp_path / "out.jsonl").read_text())
        results = [st["result"] for st in row["steps"]
                   if st["kind"] == "tool_call"]
        assert "step one step one" in results[0]

    def test_multi_label_excluded(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.json").write_text(json.dumps(_record(
            {"Step repetition": "yes", "Trajectory restart": "yes"})))
        stats = convert_mast(src, tmp_path / "out.jsonl")
        assert stats.converted == 0
        assert stats.excluded_multi_label == 1

    def test_uncovered_behaviour_excluded(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.json").write_text(json.dumps(_record(
            {"Invented content": "yes"})))  # no detector targets it
        stats = convert_mast(src, tmp_path / "out.jsonl")
        assert stats.excluded_no_covered_label == 1

    def test_unannotated_excluded(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.json").write_text(json.dumps(
            {"problem_statement": ["t"], "trajectory": []}))
        stats = convert_mast(src, tmp_path / "out.jsonl")
        assert stats.excluded_no_annotation == 1

    def test_no_signal_excluded(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.json").write_text(json.dumps(_record(
            {"Step repetition": "yes"}, trajectory=[
                {"role": "user", "content": ["go"]},
                {"role": "assistant", "content": ["one"]},
            ])))
        stats = convert_mast(src, tmp_path / "out.jsonl")
        assert stats.excluded_no_signal == 1 and stats.converted == 0

    def test_unreadable_counted_not_fatal(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "bad.json").write_text("{not json")
        (src / "good.json").write_text(json.dumps(
            _record({"Step repetition": "yes"})))
        stats = convert_mast(src, tmp_path / "out.jsonl")
        assert stats.converted == 1 and stats.excluded_unreadable == 1

    def test_no_flag_is_not_yes(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.json").write_text(json.dumps(_record(
            {"Step repetition": "no", "Trajectory restart": "NO"})))
        stats = convert_mast(src, tmp_path / "out.jsonl")
        assert stats.excluded_no_covered_label == 1

    def test_mapping_covers_ten_modes(self):
        covered = set(OPTION_TO_MODE.values())
        assert {"FM-1.2", "FM-1.3", "FM-1.5", "FM-2.1", "FM-2.2",
                "FM-2.3", "FM-2.4", "FM-2.5", "FM-2.6",
                "FM-3.1", "FM-3.2"} == covered

    def test_cli_command(self, tmp_path, capsys):
        from approximately.cli import main

        src = tmp_path / "src"
        src.mkdir()
        (src / "a.json").write_text(json.dumps(
            _record({"Step repetition": "yes"})))
        rc = main(["convert-mast", str(src), str(tmp_path / "out.jsonl")])
        assert rc == 0
        assert "converted 1" in capsys.readouterr().out

    def test_cli_nothing_converted_exits_one(self, tmp_path):
        from approximately.cli import main

        src = tmp_path / "src"
        src.mkdir()
        rc = main(["convert-mast", str(src), str(tmp_path / "out.jsonl")])
        assert rc == 1
