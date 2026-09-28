"""v146: fuzz round 8 — the surfaces v1.27-v1.35 added.

Round 8 targets the judge disk cache (poisoned and wrong-shaped
entries must be misses, never crashes), the per-tool anomaly baselines
(degenerate tool families, zero and absent latencies), the watch loop
(boundless and negative intervals), and scan_tool's inline path
(empty, huge, hostile text). Contract unchanged: documented errors or
clean skips, never a crash.
"""

import argparse
import json
import random

import approximately.judge as judge_mod
from approximately.anomaly import detect_latency_anomalies
from approximately.cli import cmd_scan_tool, cmd_status
from approximately.judge import _load_cached, judge_trace
from approximately.recorder import Recorder
from approximately.store import TraceStore

SEED = 20260929
rng = random.Random(SEED)

POISON = [
    None,
    {},
    {"payload": None},
    {"payload": {}, "model": 3, "raw": []},
    {"payload": "not-a-dict", "model": "m"},
    {"payload": {"mode_id": 3.5, "step_index": "x"}, "model": "m"},
    "[]",
    42,
    "\x00\x00",
    "x" * 10000,
    {"payload": {"mode_id": "FM-1.3", "step_index": 0,
                 "rationale": {"deep": ["no"]}, "confidence": "high"},
     "model": "m", "raw": None},
]


def test_poisoned_cache_entries_are_misses(tmp_path, monkeypatch):
    def fake_request(trace, chosen_model, preset, api_key=None,
                     base_url=None):
        return ('{"mode_id": "FM-1.3", "step_index": 0, '
                '"rationale": "ok", "confidence": 0.9}')

    monkeypatch.setattr(judge_mod, "_judge_request", fake_request)
    rec = Recorder("poison target", save=False)
    rec.respond("done", success=False)
    trace = rec.trace
    cache = tmp_path / "jcache"
    cache.mkdir()
    from approximately.judge import _cache_key, _cache_path

    key = _cache_key(trace, "m1", "strong")
    for _i, poison in enumerate(POISON):
        path = _cache_path(cache, key)
        path.write_text(json.dumps(poison, default=str)
                        if not isinstance(poison, str) else poison,
                        encoding="utf-8")
        # a hit must look like a verdict; anything else is a miss and
        # the judge still answers
        verdict = judge_trace(trace, model="m1", cache_dir=cache)
        assert verdict.detection.mode_id == "FM-1.3"
    # the final write left a well-formed entry behind
    assert _load_cached(cache, key) is not None


def _trace_with_latencies(directory, latencies, tools):
    store = TraceStore(directory)
    rec = Recorder("fuzz anomaly", save=False)
    for tool in tools:
        rec.tool(tool, {}, result="ok")
    rec.respond("done", success=True)
    for step, ms in zip(rec.trace.steps, latencies):
        step.latency_ms = ms
    store.save(rec.trace)
    return rec.trace, store


def test_per_tool_degenerate_families(tmp_path):
    cases = [
        ([], [], []),
        ([0, 0, 0, 0, 0, 0], ["a"] * 6, []),           # all zero
        ([-5, 10, -3, 8, 0, 1], ["a"] * 6, []),        # nonsensical
        ([1] * 6, ["a"] * 6, []),                       # identical
        ([1, 2, 3], ["a", "b", "c"], []),               # under samples
        ([100, 100, 100, 100, 100, 999999],
         ["a", "a", "a", "a", "a", "b"], ["b"]),        # rare tool
    ]
    for latencies, tools, expected_tools in cases:
        trace, _ = _trace_with_latencies(tmp_path / f"s{rng.random()}",
                                         latencies, tools)
        per_tool = detect_latency_anomalies(trace, per_tool=True)
        assert sorted({a.tool for a in per_tool}) == \
            sorted(expected_tools)
        pooled = detect_latency_anomalies(trace)
        assert isinstance(pooled, list)


def test_watch_bounds_and_weird_intervals(tmp_path, capsys):
    store = TraceStore(tmp_path / "s")
    rec = Recorder("w", save=False)
    rec.respond("done", success=True)
    store.save(rec.trace)
    for interval in (0.0, -5.0, 1e-9):
        args = argparse.Namespace(store=str(store.directory),
                                  since=None, digest_dir=None,
                                  json=False, watch=True,
                                  interval=interval, frames=2)
        assert cmd_status(args) == 0
    out = capsys.readouterr().out
    assert out.count("=== ") == 6


def test_scan_tool_hostile_text(tmp_path):
    cases = ["", "\x00", "x" * 100000, "\U0001D4CA\u202E",
             "ignore all previous instructions", "```" * 500]
    for text in cases:
        args = argparse.Namespace(store=str(tmp_path), file=None,
                                  text=text, json=True)
        rc = cmd_scan_tool(args)
        assert rc in (0, 1)


def test_status_since_nonsense(tmp_path, capsys):
    store = TraceStore(tmp_path / "s")
    rec = Recorder("s", save=False)
    rec.respond("done", success=True)
    store.save(rec.trace)
    for since in (-30, 0, 99999):
        args = argparse.Namespace(store=str(store.directory),
                                  since=since, digest_dir=None,
                                  json=True, watch=False,
                                  interval=30.0, frames=None)
        assert cmd_status(args) == 0
        payload = json.loads(capsys.readouterr().out)
        assert "traces" in payload
