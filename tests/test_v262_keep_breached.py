"""Night VI, round 4: the stamp survives housekeeping.

``clean --keep-breached`` keeps runs the live Budget rails stamped as
breached no matter their age or the count ceiling — housekeeping must
not destroy breach evidence before the postmortem reads it.  The
predicate behind the guard is store.stamped_breach, the same one the
ci gate and the fleet surfaces count with.  The init workflow
template gates on breaches too.
"""

import json

from approximately.budget import Budget
from approximately.cli import main
from approximately.fleet import _budget_breaches
from approximately.recorder import Recorder
from approximately.scaffold import init_scaffold
from approximately.store import TraceStore, stamped_breach


def _seed(store_dir, breached_old=False, breached_young=False,
          clean_old=0, clean_young=2):
    store = TraceStore(store_dir)
    made = []

    def record(name, breached):
        budget = Budget(tokens=5, on_exceed="stamp") if breached \
            else None
        with Recorder(name, model="m/1", store=store,
                      budget=budget) as rec:
            rec.tool("t", tokens=500 if breached else 10)
            rec.respond("done", success=True)
        made.append(rec.trace)

    for i in range(clean_old):
        record(f"old clean {i}", False)
    for i in range(clean_young):
        record(f"young clean {i}", False)
    old_burn = young_burn = None
    if breached_old:
        record("old burn", True)
        old_burn = made[-1]
    if breached_young:
        record("young burn", True)
        young_burn = made[-1]
    # push the "old" half of the store past any cutoff by backdating
    import os
    old_ids = {t.id for t in made[:clean_old]}
    if breached_old:
        old_ids.add(old_burn.id)
    for tid in old_ids:
        os.utime(store.directory / f"{tid}.json", (1_000_000, 1_000_000))
    return store, old_burn, young_burn


def test_predicate_reads_only_the_stamp(tmp_path):
    _seed(tmp_path, breached_young=True)
    traces = TraceStore(tmp_path).list_traces()
    assert _budget_breaches(traces) == 1
    assert stamped_breach(None) is False
    assert stamped_breach("poison") is False
    assert stamped_breach({"budget": "also poison"}) is False
    assert stamped_breach({"budget": {"exceeded": "true"}}) is False


def test_clean_without_guard_removes_breaches_with_the_rest(tmp_path):
    _seed(tmp_path, breached_old=True, clean_old=2)
    store = TraceStore(tmp_path)
    removed = store.clean(keep_days=1)
    assert removed == 3  # two old clean + the old breach: fair game
    assert len(list(store.directory.glob("*.json"))) == 2  # young


def test_keep_breached_spares_the_stamp(tmp_path):
    _, old_burn, _ = _seed(tmp_path, breached_old=True, clean_old=2)
    store = TraceStore(tmp_path)
    removed = store.clean(keep_days=1, keep_breached=True)
    assert removed == 2  # only the two old clean traces
    assert (store.directory / f"{old_burn.id}.json").is_file()
    assert len(list(store.directory.glob("*.json"))) == 3


def test_keep_breached_guard_survives_max_traces(tmp_path):
    # 4 traces, ceiling 2, and the two OLDEST are clean: without the
    # guard the excess eats the old pair; with it, the old clean
    # pair still goes but a breached trace is never the victim
    store_dir = tmp_path / "s"
    _, _, _ = _seed(store_dir, breached_old=True, breached_young=True,
                    clean_old=1, clean_young=1)
    store = TraceStore(store_dir)
    removed = store.clean(keep_days=36500, max_traces=2,
                          keep_breached=True)
    assert removed == 2
    left = {p.name for p in store.directory.glob("*.json")}
    assert len(left) == 2
    survivors = [TraceStore(store_dir).load(n[:-5]) for n in left]
    assert all(stamped_breach(t.meta) for t in survivors)


def test_unreadable_files_are_not_immortal(tmp_path):
    _seed(tmp_path, breached_old=True, clean_old=2)
    store = TraceStore(tmp_path)
    poison = store.directory / "deadbeef.json"
    poison.write_text("{not json", encoding="utf-8")
    os_utime_target = poison
    import os
    os.utime(os_utime_target, (1_000_000, 1_000_000))
    removed = store.clean(keep_days=1, keep_breached=True)
    # 2 old clean + the poison go; the stamped breach is spared
    assert removed == 3
    assert not poison.exists()
    assert len(list(store.directory.glob("*.json"))) == 3


def test_dry_run_counts_match_the_real_pass(tmp_path):
    _, _, _ = _seed(tmp_path, breached_old=True, clean_old=2)
    store = TraceStore(tmp_path)
    assert len(list(store.directory.glob("*.json"))) == 5
    would = store.clean(keep_days=1, keep_breached=True, dry_run=True)
    assert would == 2
    assert len(list(store.directory.glob("*.json"))) == 5
    assert store.clean(keep_days=1, keep_breached=True) == 2


def test_cli_door_reports_the_guard(tmp_path, capsys):
    _seed(tmp_path, breached_old=True, clean_old=2)
    rc = main(["clean", "--store", str(tmp_path), "--keep-days", "1",
               "--keep-breached", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["keep_breached"] is True
    assert payload["removed"] == 2
    assert payload["remaining"] == 3


def test_init_workflow_gates_on_breaches(tmp_path):
    init_scaffold(tmp_path)
    wf = (tmp_path / ".github" / "workflows" / "agent-gate.yml"
          ).read_text(encoding="utf-8")
    assert "--max-budget-breaches 0" in wf
