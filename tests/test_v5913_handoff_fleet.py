"""v5913: the postmortem worklist walks the fleet.

The handoff --queue worklist read exactly one store — but the
failures to work off live wherever each agent ran. Positional
store paths make the fleet worklist: each store's queue in its
own order, the cap applied across the total, every brief naming
its box (the reader has to know which machine owns the failure),
the overflow counted honestly beyond the cap, and a typo'd store
answering by name. The single-store worklist is byte-identical.
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


def _failed(tmp_path, name, task):
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    store = TraceStore(tmp_path / name)
    rec = Recorder(task, model="m/1", store=store, save=False)
    rec.tool("deploy", {"env": name}, result=None,
             error="boom")
    rec.respond("done", success=False)
    store.save(rec.trace)
    return store, rec.trace


def test_the_fleet_worklist_names_each_box(tmp_path):
    _failed(tmp_path, "box-a", "the checkout crash")
    _failed(tmp_path, "box-b", "the cron hang")
    r = _run("handoff", "--queue", "5", str(tmp_path / "box-a"),
             str(tmp_path / "box-b"))
    assert r.returncode == 0, r.stderr
    assert "postmortem worklist (fleet)" in r.stdout
    assert "the checkout crash" in r.stdout
    assert "the cron hang" in r.stdout
    assert "> store: box-a" in r.stdout and \
        "> store: box-b" in r.stdout, \
        "the reader has to know which machine owns the failure"


def test_the_cap_is_across_the_total(tmp_path):
    _failed(tmp_path, "box-a", "a crash")
    _failed(tmp_path, "box-a", "another crash")
    _failed(tmp_path, "box-b", "a third crash")
    r = _run("handoff", "--queue", "2", str(tmp_path / "box-a"),
             str(tmp_path / "box-b"))
    assert r.returncode == 0, r.stderr
    assert "beyond the cap of 2" in r.stdout, \
        "the overflow is counted, not swallowed"


def test_nothing_owed_stays_honest(tmp_path):
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    for name in ("box-a", "box-b"):
        store = TraceStore(tmp_path / name)
        rec = Recorder(f"clean {name}", model="m/1", store=store,
                       save=False)
        rec.tool("deploy", {}, result="ok")
        rec.respond("done", success=True)
        store.save(rec.trace)
    r = _run("handoff", "--queue", "5", str(tmp_path / "box-a"),
             str(tmp_path / "box-b"))
    assert r.returncode == 0, r.stderr
    assert "nothing owed" in r.stdout


def test_a_typo_store_answers_by_name(tmp_path):
    _failed(tmp_path, "box-a", "a crash")
    r = _run("handoff", "--queue", "5", str(tmp_path / "box-a"),
             str(tmp_path / "typo-box"))
    assert r.returncode == 2, (
        "a silently-emptied worklist would read as caught up")
    assert "store not found" in r.stderr
    assert not (tmp_path / "typo-box").exists()


def test_the_json_wrap_carries_the_fleet_page(tmp_path):
    _failed(tmp_path, "box-a", "a crash")
    r = _run("handoff", "--queue", "5", "--json",
             str(tmp_path / "box-a"))
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert "(fleet)" not in payload["markdown"], \
        "the single-store JSON wrap keeps the old page"
    r2 = _run("handoff", "--queue", "5", "--json",
              str(tmp_path / "box-a"), str(tmp_path / "box-a"))
    payload2 = json.loads(r2.stdout)
    assert "(fleet)" in payload2["markdown"]
