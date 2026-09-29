"""v169: doctor reads the judge cache's pulse.

The judge disk cache lives outside the store, so `doctor` never saw
it. `doctor --judge-cache DIR` counts entries and names unreadable
ones — read-only, because a corrupt entry is already a safe miss at
query time and deletion stays the operator's call.
"""

import argparse
import json

from approximately.cli import cmd_doctor
from approximately.doctor import doctor
from approximately.judge import _cache_key
from approximately.recorder import Recorder


def _trace():
    rec = Recorder("cache pulse", save=False)
    rec.respond("done", success=True)
    return rec.trace


def test_healthy_cache_counts_clean(tmp_path):
    cache = tmp_path / "jcache"
    cache.mkdir()
    trace = _trace()
    key = _cache_key(trace, "m1", "strong")
    (cache / f"{key}.json").write_text(json.dumps({
        "model": "m1", "preset": "strong",
        "payload": {"mode_id": "FM-1.3", "step_index": 0,
                    "rationale": "ok", "confidence": 0.9},
        "raw": "{}"}), encoding="utf-8")
    report = doctor(tmp_path / "s", judge_cache=cache)
    assert report.judge_cache_entries == 1
    assert report.judge_cache_corrupt == 0
    assert report.judge_cache_dir == str(cache)
    prose = report.render()
    assert "judge cache: 1 entry(ies)" in prose


def test_corrupt_entries_are_named_not_deleted(tmp_path):
    cache = tmp_path / "jcache"
    cache.mkdir()
    trace = _trace()
    key = _cache_key(trace, "m1", "strong")
    (cache / f"{key}.json").write_text('{"payload": "half-baked"}',
                                       encoding="utf-8")
    (cache / "totally-broken.json").write_text("{nope",
                                               encoding="utf-8")
    report = doctor(tmp_path / "s", judge_cache=cache)
    assert report.judge_cache_entries == 0
    assert report.judge_cache_corrupt == 2
    assert "safe to delete" in report.render()
    # doctor --fix does NOT touch the cache: deletion is the
    # operator's call
    from approximately.doctor import fix_hygiene

    fix_hygiene(tmp_path / "s", report)
    assert len(list(cache.glob("*.json"))) == 2


def test_missing_cache_dir_is_silent(tmp_path):
    report = doctor(tmp_path / "s", judge_cache=tmp_path / "nope")
    assert report.judge_cache_dir == ""
    assert report.judge_cache_entries == 0


def test_cli_doctor_judge_cache_json(tmp_path, capsys):
    cache = tmp_path / "jcache"
    cache.mkdir()
    (cache / "x.json").write_text("{broken", encoding="utf-8")
    args = argparse.Namespace(store=str(tmp_path / "s"),
                              digest_dir=None,
                              judge_cache=str(cache), fix=False,
                              json=True)
    assert cmd_doctor(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["judge_cache_entries"] == 0
    assert payload["judge_cache_corrupt"] == 1
    # the --json payload also carries the annotation fields the
    # prose report has always shown
    assert "annotation_orphans" in payload


def test_mcp_doctor_judge_cache(tmp_path):
    from approximately.mcp_server import _TOOLS, ServerContext, handle_request

    schema = next(t for t in _TOOLS if t["name"] == "doctor")
    assert "judge_cache" in schema["inputSchema"]["properties"]
    cache = tmp_path / "jcache"
    cache.mkdir()
    (cache / "x.json").write_text('{"payload": 1}', encoding="utf-8")
    ctx = ServerContext(".")
    payload = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "doctor",
                   "arguments": {"judge_cache": str(cache)}},
    }, ctx)
    result = json.loads(payload["result"]["content"][0]["text"])
    assert result["judge_cache_corrupt"] == 1
