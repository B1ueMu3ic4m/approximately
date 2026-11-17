"""v596: the concurrent writers get the primitive.

Three more sites write where others may be writing: the judge
cache (parallel workers share one directory - a torn cache line
poisons every verdict read back later), the digest compaction (a
fleet watch may be appending while the compaction rewrites - the
replace is all-or-nothing instead of a torn line), and
``append_digest`` itself (a Windows sharing violation on the
digest file raised out of the watch loop; the open shares the
ledger's budget now). Each pin injects the failure it guards
against.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "approximately", *args],
        capture_output=True, text=True, cwd=str(ROOT))


def test_the_digest_append_survives_a_transient(tmp_path,
                                                monkeypatch):
    from approximately.fleet import append_digest

    real_open = Path.open
    state = {"n": 0}

    def flaky(self, *a, **kw):
        if state["n"] == 0:
            state["n"] += 1
            raise PermissionError(32, "sharing violation")
        return real_open(self, *a, **kw)

    monkeypatch.setattr(Path, "open", flaky)
    path = append_digest(tmp_path, {"ts": 1.0, "stores": []})
    assert state["n"] == 1, "the append retried once and landed"
    rows = [json.loads(ln) for ln in
            path.read_text(encoding="utf-8").splitlines()]
    assert rows == [{"ts": 1.0, "stores": []}]


def test_the_digest_append_gives_up_honestly(tmp_path,
                                             monkeypatch):
    from approximately.fleet import append_digest

    def always(self, *a, **kw):
        raise PermissionError(32, "sharing violation forever")

    monkeypatch.setattr(Path, "open", always)
    clock = {"t": 0.0}
    monkeypatch.setattr("approximately.fleet.time.monotonic",
                        lambda: clock["t"])
    monkeypatch.setattr("approximately.fleet.time.sleep",
                        lambda s: clock.__setitem__("t", clock["t"] + s))
    import pytest

    with pytest.raises(PermissionError):
        append_digest(tmp_path, {"ts": 1.0, "stores": []}), \
            "the budget runs out and names the failure"
    assert clock["t"] >= 30.0, "the budget is the ledger's 30s"


def test_the_compaction_replaces_atomically(tmp_path):
    digest = tmp_path / "d"
    digest.mkdir()
    day = digest / "digest-20261001.jsonl"
    rows = [json.dumps({
        "ts": 1791000000 + i * 3600,
        "stores": [{"name": "s", "path": "/x", "traces": 1,
                    "est_spend": 1.0 + i,
                    "spend_unpriced_tokens": 0}],
        "worsening": []}, sort_keys=True) for i in range(4)]
    day.write_text("\n".join(rows) + "\n", encoding="utf-8")
    old_day = digest / "digest-20260901.jsonl"
    old_day.write_text(json.dumps({
        "ts": 1789000000,
        "stores": [], "worsening": []}, sort_keys=True) + "\n",
        encoding="utf-8")
    from approximately.fleet import compact_digests

    report = compact_digests(digest)
    assert report["after"] == 1, \
        "each day collapses to its last snapshot"
    kept = [json.loads(ln) for ln in
            day.read_text(encoding="utf-8").splitlines() if ln]
    assert len(kept) == 1, \
        "the day keeps exactly what the trend reads: its final state"
    assert kept[0]["stores"][0]["est_spend"] == 4.0, \
        "the last snapshot's spend survives the collapse"
    leftovers = list(digest.glob("*.tmp"))
    assert not leftovers, \
        "a crash mid-compaction must not leave a torn digest"


def test_the_judge_cache_writes_atomically(tmp_path):
    from approximately.judge import _cache_path

    cache = tmp_path / "cache"
    cache.mkdir()
    key = "abc123"
    out = _cache_path(cache, key)
    from approximately.store import atomic_write

    atomic_write(out, json.dumps({"model": "m", "verdict": 1}))
    back = json.loads(out.read_text(encoding="utf-8"))
    assert back["model"] == "m"
    assert not list(cache.glob("*.tmp")), \
        "a torn cache line poisons every verdict read back later"


def test_the_fleet_watch_still_appends(tmp_path):
    store_dir = tmp_path / "s"
    store_dir.mkdir()
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    store = TraceStore(store_dir)
    rec = Recorder("digest source", model="m/1", store=store,
                   save=False)
    rec.tool("deploy", {}, result="ok")
    rec.respond("done", success=True)
    store.save(rec.trace)
    from approximately.fleet import append_digest, digest_snapshot, survey

    snap = digest_snapshot(survey([str(store_dir)]))
    path = append_digest(tmp_path / "d", snap)
    rows = [json.loads(ln) for ln in
            path.read_text(encoding="utf-8").splitlines() if ln]
    assert rows and rows[0]["stores"][0]["traces"] == 1
