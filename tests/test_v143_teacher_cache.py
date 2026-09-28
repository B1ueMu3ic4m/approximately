"""v143: the distill loop learns to remember too.

`teacher_labeler` feeds every trace through the judge; relabeling a
dataset re-asks every question. With `cache_dir` the second pass is
free — `export-dataset --teacher-cache DIR` and `export-sft
--teacher-cache DIR` grow the flag, and `benchmark --judge-cache`
already had it.
"""

import argparse
import json

import approximately.distill as distill_mod
from approximately.cli import cmd_export_dataset
from approximately.distill import teacher_labeler
from approximately.recorder import Recorder


def _failing_trace(task):
    rec = Recorder(task, save=False)
    rec.tool("deploy", {"env": "prod"}, result=None, error="timeout")
    rec.respond("gave up", success=False)
    return rec.trace


def test_teacher_labeler_second_pass_is_free(monkeypatch, tmp_path):
    calls = []

    def fake_request(trace, chosen_model, preset, api_key=None,
                     base_url=None):
        calls.append(trace.task)
        return ('{"mode_id": "FM-1.3", "step_index": 0, '
                '"rationale": "deploy timed out", "confidence": 0.9}')

    import approximately.judge as judge_mod

    monkeypatch.setattr(judge_mod, "_judge_request", fake_request)
    labeler = teacher_labeler("test-model",
                              cache_dir=tmp_path / "jcache")
    assert labeler(_failing_trace("run a")) == "FM-1.3"
    assert labeler(_failing_trace("run a")) == "FM-1.3"
    assert len(calls) == 1


def test_low_confidence_labels_none(monkeypatch, tmp_path):
    def fake_judge(trace, **kwargs):
        class Det:
            mode_id = "FM-1.3"
            confidence = 0.3
        class V:
            detection = Det
        return V()

    monkeypatch.setattr(distill_mod, "judge_trace", fake_judge)
    labeler = teacher_labeler("test-model", cache_dir=tmp_path / "c")
    assert labeler(_failing_trace("unsure")) is None


def test_export_dataset_teacher_cache_flag_wired(tmp_path, monkeypatch,
                                                 capsys):
    calls = []

    def fake_judge(trace, model=None, base_url=None, api_key=None,
                   cache_dir=None):
        calls.append(cache_dir)
        class Det:
            mode_id = "FM-1.3"
            confidence = 0.9
        class V:
            detection = Det
        return V()

    monkeypatch.setattr(distill_mod, "judge_trace", fake_judge)
    store = tmp_path / "s"
    from approximately.store import TraceStore

    ts = TraceStore(store)
    ts.save(_failing_trace("one"))
    out = tmp_path / "ds.jsonl"
    args = argparse.Namespace(store=str(store), output=str(out),
                              teacher="test-model",
                              teacher_cache=str(tmp_path / "jcache"),
                              json=False)
    assert cmd_export_dataset(args) == 0
    assert calls and all(c is not None for c in calls)
    assert out.is_file()
    rows = [json.loads(line) for line in
            out.read_text(encoding="utf-8").splitlines()]
    assert rows and rows[0].get("label") == "FM-1.3"
