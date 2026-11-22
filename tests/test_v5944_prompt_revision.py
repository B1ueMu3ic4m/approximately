"""v5944: the judge cache key covers the prompt it answers for.

``_cache_key`` hashed model + preset + trace — but the preset NAME
is not the prompt: a prompt fix or a taxonomy addition shipped in
a release left every cached verdict produced by the OLD words,
served forever to a warm cache (a bill for stale judgments). The
key now includes the static half of what the judge actually
answers for — the template plus the taxonomy block interpolated
into it — so the release that changes the words invalidates the
verdicts the old words produced. One-time cost: every existing
entry misses once after the upgrade, which is the honest price of
a prompt change.
"""


import pytest

import approximately.judge as judge_mod
from approximately.judge import _prompt_revision, cache_stats, judge_trace
from approximately.recorder import Recorder

try:
    import openai  # noqa: F401
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False


def _failure(i=0):
    rec = Recorder(f"prompt revision target {i}", save=False)
    rec.tool("deploy", {}, result=None, error="boom")
    rec.respond("done", success=False)
    return rec.trace


def test_the_revision_tracks_the_words():
    revision = _prompt_revision("strong")
    assert revision == _prompt_revision("strong"), \
        "one preset, one revision: deterministic"
    assert _prompt_revision("strong") != _prompt_revision("local"), \
        "different templates answer under different revisions"
    original = judge_mod.PRESETS["strong"]
    try:
        judge_mod.PRESETS["strong"] = original.replace(
            "meticulous", "extremely meticulous")
        assert _prompt_revision("strong") != revision, \
            "a one-word prompt fix changes the revision"
    finally:
        judge_mod.PRESETS["strong"] = original
    original_taxonomy = judge_mod._taxonomy_block
    try:
        judge_mod._taxonomy_block = (lambda compact=False:
                                     original_taxonomy(
                                         compact=compact) + " FM-9.9")
        assert _prompt_revision("strong") != revision, \
            "a taxonomy addition changes the revision too"
    finally:
        judge_mod._taxonomy_block = original_taxonomy


def _stub_request(text='{"mode_id": "FM-1.3", "confidence": 0.9}'):
    def _reply(trace, chosen_model, preset,
               api_key=None, base_url=None):
        return text
    return _reply


@pytest.mark.skipif(not HAS_OPENAI, reason="openai not installed")
def test_old_words_never_serve_new_ones(tmp_path, monkeypatch):
    cache = tmp_path / "jcache"
    trace = _failure()
    monkeypatch.setattr(judge_mod, "_judge_request",
                        _stub_request('{"mode_id": "FM-1.3", '
                                     '"rationale": "old words", '
                                     '"confidence": 0.9}'))
    cache_stats(reset=True)
    old_verdict = judge_trace(trace, model="m", cache_dir=cache)
    assert cache_stats()["misses"] == 1
    # the release ships a prompt fix: the words change
    original = judge_mod.PRESETS["strong"]
    monkeypatch.setattr(judge_mod, "PRESETS", {
        **judge_mod.PRESETS,
        "strong": original.replace("meticulous", "very meticulous")})
    monkeypatch.setattr(judge_mod, "_judge_request",
                        _stub_request('{"mode_id": "FM-1.3", '
                                      '"rationale": "new words", '
                                      '"confidence": 0.9}'))
    cache_stats(reset=True)
    new_verdict = judge_trace(trace, model="m", cache_dir=cache)
    stats = cache_stats()
    assert stats["misses"] == 1 and stats["hits"] == 0, stats
    assert new_verdict.rationale == "new words", (
        "the new words are asked fresh, never answered from the "
        "old entry")
    assert old_verdict.rationale == "old words"
    # and the new entry caches: the same words asked again hit
    cache_stats(reset=True)
    again = judge_trace(trace, model="m", cache_dir=cache)
    assert cache_stats()["hits"] == 1
    assert again.rationale == "new words"
