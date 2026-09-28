"""v149: the cache shows its work.

`cache_stats()` reports hits and misses since process start (reset
after reading), `export-dataset --teacher-cache` prints the tally
after a run, and a cold cache followed by a relabel shows the whole
story: misses first, then all hits.
"""

import argparse

import approximately.judge as judge_mod
from approximately.cli import cmd_export_dataset
from approximately.judge import cache_stats, judge_trace
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _reply(trace, chosen_model, preset, api_key=None, base_url=None):
    return ('{"mode_id": "FM-1.3", "step_index": 0, '
            '"rationale": "deploy timed out", "confidence": 0.9}')


def _trace(task):
    rec = Recorder(task, save=False)
    rec.tool("deploy", {"env": "prod"}, result=None, error="timeout")
    rec.respond("gave up", success=False)
    return rec.trace


def test_stats_count_hits_and_misses(tmp_path, monkeypatch):
    monkeypatch.setattr(judge_mod, "_judge_request", _reply)
    cache = tmp_path / "jcache"
    cache_stats(reset=True)
    judge_trace(_trace("a"), model="m", cache_dir=cache)
    judge_trace(_trace("a"), model="m", cache_dir=cache)
    judge_trace(_trace("b"), model="m", cache_dir=cache)
    stats = cache_stats(reset=True)
    assert stats == {"hits": 1, "misses": 2}
    assert cache_stats() == {"hits": 0, "misses": 0}


def test_export_dataset_prints_cache_tally(tmp_path, monkeypatch,
                                           capsys):
    monkeypatch.setattr(judge_mod, "_judge_request", _reply)
    store = tmp_path / "s"
    ts = TraceStore(store)
    ts.save(_trace("one"))
    args = argparse.Namespace(store=str(store),
                              output=str(tmp_path / "ds.jsonl"),
                              teacher="test-model",
                              teacher_cache=str(tmp_path / "jcache"),
                              json=False)
    assert cmd_export_dataset(args) == 0
    out = capsys.readouterr().out
    assert "judge cache: 0 hit(s), 1 miss(es)" in out
    # a relabel is free
    args2 = argparse.Namespace(store=str(store),
                               output=str(tmp_path / "ds2.jsonl"),
                               teacher="test-model",
                               teacher_cache=str(tmp_path / "jcache"),
                               json=False)
    assert cmd_export_dataset(args2) == 0
    out2 = capsys.readouterr().out
    assert "judge cache: 1 hit(s), 0 miss(es)" in out2
