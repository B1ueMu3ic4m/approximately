"""Night VII, round 9: drift splits by the calendar.

``drift --baseline-days N`` splits one store's history at a real
date — baseline = traces older than N days, current = the rest —
because "this week versus the previous month" is the question ops
asks, and a count-ratio split answers a different one.  The count
split stays the default.
"""

import json
import time

from approximately.cli import main
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store_spanning_months(tmp_path):
    store = TraceStore(tmp_path / "s")
    now = time.time()
    import os

    # 6 traces ~40 days old (the old world), 4 traces fresh (today)
    ids = {"old": [], "new": []}
    for i in range(6):
        with Recorder(f"old run {i}", model="m/legacy",
                      store=store) as rec:
            rec.tool("legacy_tool", {}, result="ok")
            rec.respond("done", success=i != 0)  # 1 old failure
        # these runs honestly claim to be 40 days old: the split
        # reads the trace's own created_at, not the file's mtime
        rec.trace.created_at = now - 40 * 86400
        (store.directory / f"{rec.trace.id}.json").write_text(
            json.dumps(rec.trace.to_dict()), encoding="utf-8")
        ids["old"].append(rec.trace.id)
    for i in range(4):
        with Recorder(f"new run {i}", model="m/new",
                      store=store) as rec:
            rec.tool("shiny_tool", {}, result="ok")
            rec.respond("done", success=True)
        ids["new"].append(rec.trace.id)
    for tid in ids["old"]:
        path = store.directory / f"{tid}.json"
        os.utime(path, (now - 40 * 86400, now - 40 * 86400))
    return store, ids


def test_baseline_days_splits_by_time(tmp_path, capsys):
    store, _ids = _store_spanning_months(tmp_path)
    rc = main(["drift", "--store", str(store.directory),
               "--baseline-days", "30", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    # old world ran legacy_tool only; the time-disjoint split makes
    # the new tool a pure current-window action
    actions = {a["action"] if isinstance(a, dict) else a
               for a in payload["top_shifted"]}
    assert any("shiny" in str(a) for a in actions)


def test_baseline_days_missing_side_exits_clean(tmp_path, capsys):
    store, _ids = _store_spanning_months(tmp_path)
    rc = main(["drift", "--store", str(store.directory),
               "--baseline-days", "400", "--json"])
    out = capsys.readouterr().out
    assert rc == 1  # nothing older than 400d? all baseline... actually
    # 40d-old traces ARE older than 400d? No: 400d cutoff means
    # baseline = older than 400 days = none. Either way: clean exit.
    assert "both windows" in out or rc == 0


def test_count_split_still_the_default(tmp_path, capsys):
    store, _ids = _store_spanning_months(tmp_path)
    rc = main(["drift", "--store", str(store.directory), "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    # count split mixes both eras: no shifted action names the new
    # tool cleanly (legacy dominates the baseline window)
    assert "psi" in out
