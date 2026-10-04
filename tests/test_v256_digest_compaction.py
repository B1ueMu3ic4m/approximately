"""v256: the digest drain.

A watch at a 10-second interval writes 8,640 snapshot lines a day;
the trend reader only ever looks at the LAST snapshot of each day.
`fleet --compact-digests` collapses each day file to exactly what
the trend reads — the final state plus the day's snapshot count —
so the history stays complete in meaning while the disk stops
filling.  Dry-run honest; torn tail lines follow the same rule as
the trend reader; today's file compacts too, and the next append
continues from the compacted form.
"""

import json
import time

from approximately.cli import main
from approximately.fleet import (
    append_digest,
    compact_digests,
    digest_snapshot,
    summarize_trend,
    survey,
    trend_days,
)
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _digest_dir(tmp_path, days=3, per_day=5):
    import datetime

    digest = tmp_path / "digest"
    digest.mkdir(parents=True)
    store = TraceStore(tmp_path / "s")
    rec = Recorder("calm", store=store, save=False)
    rec.respond("done", success=True)
    summaries = survey([store.directory])
    now = time.time()
    for d in range(days):
        # noon of each day: snapshots land well inside their own
        # date no matter what wall-clock hour the test runs at (a
        # now-minus-k*60 line crossing midnight used to split day 0
        # in two whenever the suite ran just after 00:00)
        day_noon = datetime.datetime.fromtimestamp(
            now - d * 86400).replace(hour=12, minute=0, second=0,
                                     microsecond=0)
        stamp = day_noon.strftime("%Y%m%d")
        path = digest / f"digest-{stamp}.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            for k in range(per_day):
                snap = digest_snapshot(summaries)
                snap["ts"] = day_noon.timestamp() + k
                fh.write(json.dumps(snap, sort_keys=True) + "\n")
    return digest, store.directory


def test_compaction_keeps_the_last_state_per_day(tmp_path):
    digest, _ = _digest_dir(tmp_path)
    report = compact_digests(digest)
    assert report["before"] == 15 and report["after"] == 3
    assert all(f["after"] == 1 for f in report["files"])


def test_trend_reads_identically_after_compaction(tmp_path):
    digest, _ = _digest_dir(tmp_path)
    before = summarize_trend(trend_days(digest))
    compact_digests(digest)
    after = summarize_trend(trend_days(digest))
    assert len(after["days"]) == len(before["days"]) == 3
    assert [d["traces"] for d in after["days"]] == \
        [d["traces"] for d in before["days"]]
    assert after["verdict"] == before["verdict"]


def test_dry_run_writes_nothing(tmp_path):
    digest, _ = _digest_dir(tmp_path)
    files_before = {p.name: p.read_text(encoding="utf-8")
                    for p in digest.glob("digest-*.jsonl")}
    report = compact_digests(digest, dry_run=True)
    assert report["before"] == 15
    files_after = {p.name: p.read_text(encoding="utf-8")
                   for p in digest.glob("digest-*.jsonl")}
    assert files_before == files_after


def test_append_continues_from_the_compacted_form(tmp_path):
    digest, store_dir = _digest_dir(tmp_path, days=1, per_day=4)
    compact_digests(digest)
    summaries = survey([store_dir])
    append_digest(digest, digest_snapshot(summaries))
    # the day file now holds the compacted line + the new append
    day_file = next(digest.glob("digest-*.jsonl"))
    lines = [line for line in day_file.read_text(
        encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 2
    days = trend_days(digest)
    assert days[0]["snapshots"] >= 2


def test_single_snapshot_days_are_untouched(tmp_path):
    digest, _ = _digest_dir(tmp_path, days=2, per_day=1)
    report = compact_digests(digest)
    assert report["files"] == []


def test_torn_tail_line_is_dropped_not_fatal(tmp_path):
    digest, _ = _digest_dir(tmp_path, days=1, per_day=3)
    day_file = next(digest.glob("digest-*.jsonl"))
    day_file.write_text(
        day_file.read_text(encoding="utf-8") + '{"torn"\n',
        encoding="utf-8")
    report = compact_digests(digest)
    assert report["after"] == 1
    kept = json.loads(day_file.read_text(encoding="utf-8"))
    assert isinstance(kept, dict) and "stores" in kept


def test_cli_door(tmp_path, capsys):
    digest, _ = _digest_dir(tmp_path)
    code = main(["fleet", "--compact-digests",
                 "--digest-dir", str(digest)])
    assert code == 0
    out = capsys.readouterr().out
    assert "collapsed to 1" in out


def test_cli_door_missing_dir_refuses(tmp_path, capsys):
    code = main(["fleet", "--compact-digests",
                 "--digest-dir", str(tmp_path / "nope")])
    assert code == 2
    assert "no such digest directory" in capsys.readouterr().err


def test_watch_compacts_on_start(tmp_path):
    from approximately.fleet import watch_fleet

    digest, store_dir = _digest_dir(tmp_path, days=2, per_day=4)
    watch_fleet([store_dir], digest, 0.0, iterations=1,
                alert_cooldown=3600.0, clock=lambda: 0.0)
    # every prior day collapsed to one line; today's file compacted
    # too, then the cycle's own append landed after it
    for path in digest.glob("digest-*.jsonl"):
        lines = [line for line in path.read_text(
            encoding="utf-8").splitlines() if line.strip()]
        assert len(lines) <= 2
    # and the history still reads as complete days
    summary = summarize_trend(trend_days(digest))
    assert len(summary["days"]) == 2


def test_watch_compacts_again_at_midnight(tmp_path):
    from approximately.fleet import watch_fleet

    digest, store_dir = _digest_dir(tmp_path, days=1, per_day=3)
    real_append = append_digest
    calls = {"n": 0}

    def alternating_append(d, snap):
        # simulate a midnight crossing: the second cycle writes
        # into a NEW day file
        calls["n"] += 1
        import datetime
        if calls["n"] >= 2:
            stamp = datetime.datetime.fromtimestamp(
                time.time() + 86400).strftime("%Y%m%d")
            path = d / f"digest-{stamp}.jsonl"
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(snap, sort_keys=True) + "\n")
            return path
        return real_append(d, snap)

    import approximately.fleet as fleet_mod
    fleet_mod.append_digest = alternating_append
    try:
        watch_fleet([store_dir], digest, 0.0, iterations=3,
                    alert_cooldown=3600.0, clock=lambda: 0.0)
    finally:
        fleet_mod.append_digest = real_append
    for path in digest.glob("digest-*.jsonl"):
        lines = [line for line in path.read_text(
            encoding="utf-8").splitlines() if line.strip()]
        assert len(lines) <= 2, (path.name, len(lines))
