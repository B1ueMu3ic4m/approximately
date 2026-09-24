"""v85: doctor detects the legacy agent identity.

Traces recorded before v0.50 carry the actor in step
``meta["agent"]``; the field ``Step.agent`` is what the scorecard,
detectors, and reports read first. The doctor flags affected files
(informational — not an unhealthy verdict) with the migration hint.
"""

import json

from approximately.cli import build_parser
from approximately.doctor import doctor
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _mixed_store(tmp_path):
    store = TraceStore(str(tmp_path / "s"))
    # modern identity: Step.agent set, serialized at top level
    modern = Recorder("modern", save=False)
    modern.tool("bash", {"cmd": "x"}, result="y", agent="worker")
    modern.respond("done")
    store.save(modern.trace)
    # legacy identity: agent only inside step meta
    legacy = Recorder("legacy", save=False)
    legacy.tool("bash", {"cmd": "y"}, result="z")
    legacy.respond("done")
    data = legacy.trace.to_dict()
    data["id"] = "legacy-0001"
    data["steps"][0]["meta"]["agent"] = "old-worker"
    (store.directory / "legacy-0001.json").write_text(
        json.dumps(data), encoding="utf-8")
    return store


def test_doctor_flags_legacy_agent_files(tmp_path):
    store = _mixed_store(tmp_path)
    report = doctor(store.directory)
    assert report.legacy_agents == ["legacy-0001.json"]


def test_legacy_agents_do_not_break_health(tmp_path):
    # informational only: a store can be healthy and still carry legacy
    store = _mixed_store(tmp_path)
    report = doctor(store.directory)
    assert report.healthy
    assert report.corrupt == []


def test_doctor_json_and_render_carry_the_hint(tmp_path, capsys):
    store = _mixed_store(tmp_path)
    parser = build_parser()
    args = parser.parse_args(["doctor", "--store", str(store.directory), "--json"])
    assert args.func(args) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["legacy_agents"] == ["legacy-0001.json"]

    args = parser.parse_args(["doctor", "--store", str(store.directory)])
    assert args.func(args) == 0
    out = capsys.readouterr().out
    assert "legacy meta['agent']" in out
    assert "re-save to migrate" in out


def test_modern_store_is_silent(tmp_path, capsys):
    store = TraceStore(str(tmp_path / "modern"))
    rec = Recorder("modern run", save=False)
    rec.tool("bash", {"cmd": "x"}, result="y", agent="worker")
    rec.respond("done")
    store.save(rec.trace)
    report = doctor(store.directory)
    assert report.legacy_agents == []
    assert "legacy" not in report.render()
