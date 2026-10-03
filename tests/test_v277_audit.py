"""Night VI, round 21: the composed nightly door.

``approximately audit`` is what a 3am cron runs instead of four
commands and a script: doctor (optionally repairing), the quality
gate over the store, and — with a digest dir — the fleet trend and
the spend forecast.  One report, one exit code: 0 quiet, 1 any
finding, 2 refusal.
"""

import json

from approximately.budget import Budget
from approximately.cli import main
from approximately.doctor import QUARANTINE_DIR
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _healthy_store(tmp_path):
    store = TraceStore(tmp_path / "s")
    with Recorder("calm", model="m/1", store=store) as rec:
        rec.tool("t", tokens=10)
        rec.respond("done", success=True)
    return store


def _burned_store(tmp_path, clean=2):
    store = TraceStore(tmp_path / "s")
    for i in range(clean):
        with Recorder(f"calm {i}", model="m/1", store=store) as rec:
            rec.respond("done", success=True)
    budget = Budget(tokens=5)
    with Recorder("burn", model="m/1", store=store,
                  budget=budget) as rec:
        rec.tool("t", tokens=500)
        rec.respond("done", success=True)
    return store


def _audit(store, extra=()):
    argv = ["audit", "--store", str(store.directory),
            "--max-budget-breaches", "0", *extra]
    return argv


def test_quiet_store_audits_clean(tmp_path, capsys):
    store = _healthy_store(tmp_path)
    rc = main([*_audit(store), "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["doctor"]["healthy"] is True
    assert payload["gate"]["ok"] is True


def test_breach_fails_the_audit(tmp_path, capsys):
    store = _burned_store(tmp_path)
    rc = main([*_audit(store), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["ok"] is False
    assert payload["gate"]["ok"] is False


def test_doctor_finding_fails_without_gate(tmp_path, capsys):
    store = _healthy_store(tmp_path)
    (store.directory / "dead.json").write_text("{nope",
                                                encoding="utf-8")
    rc = main(["audit", "--store", str(store.directory),
               "--min-traces", "1", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["doctor"]["healthy"] is False
    assert payload["gate"]["ok"] is True


def test_fix_quarantines_while_auditing(tmp_path, capsys):
    store = _healthy_store(tmp_path)
    (store.directory / "dead.json").write_text("{nope",
                                                encoding="utf-8")
    rc = main(["audit", "--store", str(store.directory),
               "--min-traces", "1", "--fix", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["doctor"]["quarantined"] == ["dead.json"]
    assert (store.directory / QUARANTINE_DIR / "dead.json").is_file()


def test_forecast_ceiling_exceeded_fails(tmp_path, capsys):
    store = _healthy_store(tmp_path)
    digest = tmp_path / "d"
    digest.mkdir()
    for i, spend in enumerate([5.0, 15.0]):
        line = json.dumps({
            "ts": 1791000000 + i * 86400,
            "stores": [{"name": "s", "path": str(store.directory),
                        "traces": 1, "est_spend": spend,
                        "spend_unpriced_tokens": 0}],
            "worsening": []}, sort_keys=True)
        (digest / f"digest-2026100{i + 1}.jsonl").write_text(
            line + "\n", encoding="utf-8")
    rc = main(["audit", "--store", str(store.directory),
               "--min-traces", "1", "--digest-dir", str(digest),
               "--spend-ceiling", "10.0", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["forecast"]["days_to_ceiling"] == 0
    assert payload["ok"] is False


def test_empty_store_refuses(tmp_path, capsys):
    empty = tmp_path / "nothing"
    empty.mkdir()
    rc = main(["audit", "--store", str(empty), "--min-traces", "1"])
    capsys.readouterr()
    assert rc == 2


def test_prose_renders_each_component(tmp_path, capsys):
    store = _healthy_store(tmp_path)
    rc = main(_audit(store))
    out = capsys.readouterr().out
    assert rc == 0
    assert "doctor:    healthy" in out
    assert "gate:      all passed" in out
    assert "verdict:   quiet" in out
