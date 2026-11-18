"""v5910: verify walks the fleet.

The verify door audited exactly one store — but the evidence now
lives wherever each agent ran, and an operator's question is "is
EVERY box's evidence still good?", not "is this one?". Positional
store paths verify as ONE audit: a section per store, each verdict
labeled with its store, the exit is the WORST (an incomplete box
outranks a tampered one — unreadable evidence is the deeper
problem), --json aggregates under "stores", a typo'd store
answers by name. The single-store door is byte-identical.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "approximately", *args],
        capture_output=True, text=True, cwd=str(ROOT),
        encoding="utf-8")


def _clean(tmp_path, name):
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    store = TraceStore(tmp_path / name)
    rec = Recorder(f"fleet {name}", model="m/1", store=store,
                   save=False)
    rec.tool("deploy", {"env": name}, result="ok")
    rec.respond("done", success=True)
    store.save(rec.trace)
    return store, rec.trace


def test_two_intact_stores_verify_as_one(tmp_path):
    _clean(tmp_path, "box-a")
    _clean(tmp_path, "box-b")
    r = _run("verify", str(tmp_path / "box-a"),
             str(tmp_path / "box-b"))
    assert r.returncode == 0, r.stderr
    assert "== box-a ==" in r.stdout and "== box-b ==" in r.stdout
    assert "1 intact" in r.stdout, "each section carries its totals"


def test_a_tampered_box_fails_the_fleet_by_name(tmp_path):
    _clean(tmp_path, "box-a")
    _clean(tmp_path, "box-b")
    victim = tmp_path / "box-a"
    trace_file = next(f for f in victim.glob("*.json"))
    data = json.loads(trace_file.read_text(encoding="utf-8"))
    data["steps"][0]["result"] = "edited elsewhere"
    trace_file.write_text(json.dumps(data), encoding="utf-8")
    r = _run("verify", str(tmp_path / "box-a"),
             str(tmp_path / "box-b"))
    assert r.returncode == 1, (
        "a tampered box fails the whole fleet audit")
    assert "TAMPERED" in r.stdout


def test_an_incomplete_box_outranks_a_tampered_one(tmp_path):
    _clean(tmp_path, "box-a")
    _clean(tmp_path, "box-b")
    victim = tmp_path / "box-a"
    trace_file = next(f for f in victim.glob("*.json"))
    data = json.loads(trace_file.read_text(encoding="utf-8"))
    data["steps"][0]["result"] = "edited elsewhere"
    trace_file.write_text(json.dumps(data), encoding="utf-8")
    (tmp_path / "box-b" / "corrupt01ab.json").write_text(
        "{torn", encoding="utf-8")
    r = _run("verify", str(tmp_path / "box-a"),
             str(tmp_path / "box-b"))
    assert r.returncode == 6, (
        "unreadable evidence is the deeper problem: 6 dominates 1")
    assert "INCOMPLETE AUDIT" in r.stdout


def test_a_typo_store_answers_by_name(tmp_path):
    _clean(tmp_path, "box-a")
    r = _run("verify", str(tmp_path / "box-a"),
             str(tmp_path / "typo-box"))
    assert r.returncode == 2, (
        "a silently-verified empty store would read as good news")
    assert "store not found" in r.stderr
    assert not (tmp_path / "typo-box").exists()


def test_the_json_aggregates_under_stores(tmp_path):
    _clean(tmp_path, "box-a")
    _clean(tmp_path, "box-b")
    r = _run("verify", str(tmp_path / "box-a"),
             str(tmp_path / "box-b"), "--json")
    payload = json.loads(r.stdout)
    assert [s["store"] for s in payload["stores"]] == \
        ["box-a", "box-b"]
    assert all(s["summary"]["intact"] == 1
               for s in payload["stores"])


def test_the_single_store_door_is_unchanged(tmp_path):
    _clean(tmp_path, "box-a")
    r = _run("--store", str(tmp_path / "box-a"), "verify", "--all")
    assert r.returncode == 0, r.stderr
    assert "== box-a ==" not in r.stdout, \
        "no positional stores: the old prose, byte for byte"
    r2 = _run("--store", str(tmp_path / "box-a"), "verify",
              "--all", "--json")
    payload = json.loads(r2.stdout)
    assert "stores" not in payload, \
        "the single-store shape gains no key"
