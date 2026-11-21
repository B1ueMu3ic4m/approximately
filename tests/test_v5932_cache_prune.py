"""v5932: the judge cache gets the operator's call.

v169 made doctor read the cache — entries counted, corrupt ones
named — and deliberately left deletion to the operator's own
hands. This is that call, made explicit and reported:
``doctor --judge-cache DIR --prune DAYS`` removes entries older
than DAYS (mtime age; a stale corrupt entry is dead weight by age,
a fresh one stays named), ``--dry-run`` prints the very numbers
the real prune would print without unlinking anything, unlink
failures are counted and named instead of fatal, and the report
carries the prune outcome next to the post-prune health reading.
``--prune`` without a cache dir is refused by name — the call only
ever touches the cache the operator points at.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "approximately", *args],
        capture_output=True, text=True, cwd=str(ROOT),
        encoding="utf-8")


def _cache(tmp_path, name="jc"):
    cache = tmp_path / name
    cache.mkdir()
    for nm, age, corrupt in (("fresh", 1, False),
                             ("stale", 10, False),
                             ("oldcorrupt", 20, True)):
        path = cache / f"{nm}.json"
        path.write_text("{torn" if corrupt else json.dumps(
            {"payload": {}, "model": "m1"}), encoding="utf-8")
        stamp = time.time() - age * 86400
        os.utime(path, (stamp, stamp))
    return cache


def test_prune_removes_only_the_stale(tmp_path):
    from approximately.doctor import prune_judge_cache

    cache = _cache(tmp_path)
    outcome = prune_judge_cache(cache, 7)
    assert (outcome["pruned"], outcome["kept"]) == (2, 1)
    assert outcome["failed"] == []
    assert outcome["freed_bytes"] > 0
    left = {p.name for p in cache.glob("*.json")}
    assert left == {"fresh.json"}, \
        "the fresh entry survives; stale corrupt goes too"


def test_dry_run_reports_without_deleting(tmp_path):
    from approximately.doctor import prune_judge_cache

    cache = _cache(tmp_path)
    dry = prune_judge_cache(cache, 7, dry_run=True)
    real = prune_judge_cache(_cache(tmp_path, "jc2"), 7)
    assert (dry["pruned"], dry["kept"]) == \
        (real["pruned"], real["kept"]), \
        "the dry run prints the very numbers the real prune would"
    assert len(list(cache.glob("*.json"))) == 3, \
        "a dry run deletes nothing"


def test_refusals_come_by_name(tmp_path):
    from approximately.doctor import prune_judge_cache

    try:
        prune_judge_cache(tmp_path / "nope", 7)
    except ValueError as exc:
        assert "no judge cache at" in str(exc)
    else:
        raise AssertionError("a missing cache must not prune")
    try:
        prune_judge_cache(_cache(tmp_path), -1)
    except ValueError as exc:
        assert "days must be >= 0" in str(exc)
    else:
        raise AssertionError("negative days must not prune")


def test_doctor_reports_the_prune_next_to_the_health(tmp_path):
    from approximately.doctor import doctor

    cache = _cache(tmp_path)
    report = doctor(tmp_path / "store", judge_cache=cache,
                    judge_cache_prune=7)
    assert (report.judge_cache_pruned,
            report.judge_cache_entries) == (2, 1), \
        "the health reading counts what the prune LEFT"
    payload = report.to_dict()
    assert payload["judge_cache_prune_days"] == 7
    assert payload["judge_cache_kept"] == 1
    assert "judge cache prune: pruned 2 entry(ies)" in \
        report.render()
    dry_report = doctor(tmp_path / "store",
                        judge_cache=_cache(tmp_path, "jc3"),
                        judge_cache_prune=7, judge_cache_dry_run=True)
    assert "would prune" in dry_report.render()
    assert len(list((tmp_path / "jc3").glob("*.json"))) == 3


def test_the_door_wires_prune_end_to_end(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    cache = _cache(tmp_path)
    r = _run("--store", str(store), "doctor", "--judge-cache",
             str(cache), "--prune", "7", "--json")
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["judge_cache_pruned"] == 2
    r = _run("--store", str(store), "doctor", "--prune", "7")
    assert r.returncode == 2, \
        "a prune with no cache dir is a refusal, not a shrug"
    assert "--prune needs --judge-cache" in r.stderr
