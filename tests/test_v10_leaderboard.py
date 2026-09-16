"""v0.10: benchmark --html leaderboard — rendering, escaping, CLI wiring."""

from __future__ import annotations

import json

from approximately.distill import BenchmarkResult, render_leaderboard_html


def _result(**overrides) -> BenchmarkResult:
    per_mode = {
        "FM-1.3": {"tp": 5, "fp": 1, "fn": 0, "precision": 0.83,
                   "recall": 1.0, "f1": 0.91},
        "OTHER": {"tp": 2, "fp": 3, "fn": 4, "precision": 0.4,
                  "recall": 0.33, "f1": 0.36},
    }
    if "per_mode" in overrides:
        per_mode = overrides.pop("per_mode")
    return BenchmarkResult(accuracy=overrides.pop("accuracy", 0.7),
                           macro_f1=overrides.pop("macro_f1", 0.63),
                           per_mode=per_mode)


class TestRendering:
    def test_structure_and_ordering(self):
        html = render_leaderboard_html(_result(), "rule detectors",
                                       "d.jsonl", 8)
        assert html.startswith("<!doctype html>")
        assert "Attribution leaderboard" in html
        assert "70.0%" in html and "63.0%" in html  # KPIs
        # sorted by F1: FM-1.3 (0.91) appears before OTHER (0.36)
        assert html.index("FM-1.3") < html.index("OTHER")
        assert "predictor: rule detectors" in html
        assert "d.jsonl" in html

    def test_unknown_mode_gets_fallback_label(self):
        result = _result(per_mode={"FM-XX": {
            "tp": 1, "fp": 0, "fn": 0, "precision": 1.0, "recall": 1.0,
            "f1": 1.0}})
        html = render_leaderboard_html(result, "rules")
        assert "FM-XX" in html  # id shown...
        assert "Unclassified" in html  # ...label falls back to OTHER's

    def test_empty_result_renders_placeholder(self):
        html = render_leaderboard_html(
            BenchmarkResult(accuracy=0.0, macro_f1=0.0, per_mode={}),
            "rules")
        assert "no modes scored" in html

    def test_mode_id_injection_escaped(self):
        result = _result(per_mode={'"><script>alert(1)</script>': {
            "tp": 1, "fp": 0, "fn": 0, "precision": 1.0, "recall": 1.0,
            "f1": 1.0}})
        html = render_leaderboard_html(result, "rules")
        assert "<script>" not in html

    def test_source_and_dataset_escaped(self):
        html = render_leaderboard_html(_result(), 'judge <b>x</b>',
                                       '<script>y</script>.jsonl', 3)
        assert "<b>x</b>" not in html and "<script>" not in html
        assert "&lt;b&gt;x&lt;/b&gt;" in html

    def test_bars_clamped(self):
        result = _result(per_mode={"FM-1.3": {
            "tp": 1, "fp": 0, "fn": 0, "precision": 1.5, "recall": -0.2,
            "f1": float("nan")}})
        html = render_leaderboard_html(result, "rules")
        assert "width:120px" in html      # precision clamped to 1.0
        assert html.count("width:0px") == 2  # recall -0.2 and NaN f1 -> 0
        assert "nan" not in html.lower()


class TestCliWiring:
    def _dataset(self, tmp_path):
        path = tmp_path / "ds.jsonl"
        rows = []
        for i, (label, tool) in enumerate(
                [("FM-1.3", "search"), ("FM-1.3", "search"),
                 ("OTHER", "deploy")]):
            rows.append({
                "task": f"task {i}",
                "steps": [
                    {"kind": "tool_call", "tool": tool, "args": {},
                     "result": "ok", "index": 0},
                    {"kind": "tool_call", "tool": tool, "args": {},
                     "result": "ok", "index": 1},
                ],
                "success": False,
                "label": label,
            })
        path.write_text("\n".join(json.dumps(r) for r in rows))
        return path

    def test_benchmark_writes_html(self, tmp_path):
        from approximately.cli import main

        ds = self._dataset(tmp_path)
        out = tmp_path / "board.html"
        rc = main(["--store", str(tmp_path / "store"),
                   "benchmark", str(ds), "--html", str(out)])
        assert rc == 0
        html = out.read_text()
        assert "Attribution leaderboard" in html
        assert "3 labeled traces" in html

    def test_benchmark_without_html_unchanged(self, tmp_path, capsys):
        from approximately.cli import main

        ds = self._dataset(tmp_path)
        rc = main(["--store", str(tmp_path / "store"), "benchmark", str(ds)])
        assert rc == 0
        assert "wrote leaderboard" not in capsys.readouterr().out
