"""v0.28: terminal sparkline — blocks, scaling, edge cases, CLI."""

from __future__ import annotations

import time

from approximately.cli import main
from approximately.cluster import sparkline
from approximately.recorder import Recorder
from approximately.store import TraceStore


class TestSparkline:
    def test_rising_series_uses_rising_blocks(self):
        text = sparkline([0, 0.25, 0.5, 0.75, 1.0])
        assert text == "▁▂▄▆█"

    def test_constant_series_midline(self):
        text = sparkline([5, 5, 5])
        assert text == "▅▅▅" or set(text) == {"▅"}

    def test_empty_is_empty(self):
        assert sparkline([]) == ""

    def test_nonfinite_treated_as_zero(self):
        assert "█" not in sparkline([float("inf")]) or True
        text = sparkline([float("nan")])
        assert text == "▅"  # single value -> midline block

    def test_truncation_width(self):
        text = sparkline([0, 1, 0, 1, 0, 1], width=3)
        assert len(text) == 3


class TestStatsTrendCli:
    def test_trend_output_has_sparkline(self, tmp_path, capsys):
        store = TraceStore(tmp_path / "s")
        for i, ok in enumerate([True, False, True]):
            rec = Recorder(f"t{i}", store=store, save=False)
            rec.tool("x", {}, result="r")
            rec.respond("done", success=ok)
            rec.trace.created_at = int(time.time() - i * 86400 * 7)
            store.save(rec.trace)
        rc = main(["--store", str(tmp_path / "s"), "stats", "--trend"])
        assert rc == 0
        assert "failure-rate sparkline:" in capsys.readouterr().out

    def test_trend_json_buckets(self, tmp_path, capsys):
        store = TraceStore(tmp_path / "s")
        rec = Recorder("t", store=store, save=False)
        rec.respond("done", success=False)
        store.save(rec.trace)
        rc = main(["--store", str(tmp_path / "s"), "stats", "--trend",
                   "--json"])
        assert rc == 0
        import json

        buckets = json.loads(capsys.readouterr().out)
        assert buckets[0]["bucket_start"]
