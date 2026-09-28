"""v137: the judge learns to remember — disk cache for verdicts.

Judge calls cost money and time, and the same failure gets asked the
same question by different commands (attribute, then benchmark, then
distill). With ``cache_dir`` the verdict is keyed by
(model, preset, compact trace) and stored on disk: a hit is
byte-equivalent to a fresh answer, a corrupt entry is a miss, and a
different model or preset re-asks.
"""


import pytest

import approximately.judge as judge_mod
from approximately.judge import JudgeError, judge_trace
from approximately.recorder import Recorder


@pytest.fixture()
def failing_trace():
    rec = Recorder("flaky deploy", save=False)
    rec.tool("deploy", {"env": "prod"}, result=None, error="timeout")
    rec.respond("gave up", success=False)
    return rec.trace


@pytest.fixture()
def counting_judge(monkeypatch):
    calls = []

    def fake_request(trace, chosen_model, preset, api_key=None,
                     base_url=None):
        calls.append((chosen_model, preset))
        return ('{"mode_id": "FM-1.3", "step_index": 0, '
                '"rationale": "the tool timed out", "confidence": 0.9}')

    monkeypatch.setattr(judge_mod, "_judge_request", fake_request)
    return calls


def test_second_identical_call_hits_cache(failing_trace,
                                          counting_judge, tmp_path):
    cache = tmp_path / "jcache"
    first = judge_trace(failing_trace, model="m1", cache_dir=cache)
    second = judge_trace(failing_trace, model="m1", cache_dir=cache)
    assert len(counting_judge) == 1
    assert second.detection.mode_id == first.detection.mode_id
    assert second.rationale == first.rationale
    files = list(cache.glob("*.json"))
    assert len(files) == 1


def test_different_model_reasks(failing_trace, counting_judge,
                                tmp_path):
    cache = tmp_path / "jcache"
    judge_trace(failing_trace, model="m1", cache_dir=cache)
    judge_trace(failing_trace, model="m2", cache_dir=cache)
    assert len(counting_judge) == 2
    assert len(list(cache.glob("*.json"))) == 2


def test_corrupt_cache_entry_is_a_miss(failing_trace, counting_judge,
                                       tmp_path):
    cache = tmp_path / "jcache"
    judge_trace(failing_trace, model="m1", cache_dir=cache)
    for path in cache.glob("*.json"):
        path.write_text("{not json at all", encoding="utf-8")
    verdict = judge_trace(failing_trace, model="m1", cache_dir=cache)
    assert len(counting_judge) == 2
    assert verdict.detection.mode_id == "FM-1.3"


def test_ro_cache_dir_never_fails_the_judge(failing_trace,
                                            counting_judge, tmp_path):
    ro = tmp_path / "ro"
    ro.mkdir(mode=0o500)
    verdict = judge_trace(failing_trace, model="m1", cache_dir=ro)
    assert verdict.detection.mode_id == "FM-1.3"


def test_judge_error_is_not_cached(failing_trace, monkeypatch,
                                   tmp_path):
    calls = []

    def flaky(trace, chosen_model, preset, api_key=None, base_url=None):
        calls.append(1)
        if len(calls) == 1:
            raise JudgeError("network down")
        return ('{"mode_id": "FM-1.3", "step_index": 0, '
                '"rationale": "ok", "confidence": 0.8}')

    monkeypatch.setattr(judge_mod, "_judge_request", flaky)
    cache = tmp_path / "jcache"
    with pytest.raises(JudgeError):
        judge_trace(failing_trace, model="m1", cache_dir=cache)
    verdict = judge_trace(failing_trace, model="m1", cache_dir=cache)
    assert verdict.detection.mode_id == "FM-1.3"
    assert list(cache.glob("*.json"))
