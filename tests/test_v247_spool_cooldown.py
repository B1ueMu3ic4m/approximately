"""v247: the spool pager is naturally one-shot — pinned.

Suspicion: the spool watch could storm like the fleet watch, so a
cooldown was drafted.  The pin tests say otherwise, and the draft
was rolled back: imported files archive out of the spool (so the
same failure cannot re-page), dry runs never count failures (so
they never page), and unparsed files never page (they are not run
failures — a human reads them).  Kept from the round: spool_pass
now aggregates trace_ids, so `spool --json` lines name exactly
which runs landed in that pass.
"""

import json
from pathlib import Path

from approximately.recorder import Recorder
from approximately.spool import spool_pass, watch_spool
from approximately.store import TraceStore


class _Spy:
    def __init__(self):
        self.bodies = []

    def __call__(self, store, outcome, url):
        self.bodies.append(outcome)
        return "200"


def _failing_file(spool: Path, name: str):
    rec = Recorder(f"broken {name}", save=False)
    rec.tool("deploy", {}, error="boom")
    rec.respond("gave up", success=False)
    (spool / name).write_text(
        json.dumps(rec.trace.to_dict()) + "\n", encoding="utf-8")


def test_a_failure_pages_exactly_once(tmp_path):
    spool = tmp_path / "spool"
    spool.mkdir()
    _failing_file(spool, "run.jsonl")
    store = TraceStore(tmp_path / "s")
    spy = _Spy()
    watch_spool(store, spool, interval=0.0, max_passes=3,
                webhook_url="http://x/", notify=spy)
    # pass 1 imports and archives; passes 2-3 see an empty spool
    assert len(spy.bodies) == 1
    assert spy.bodies[0]["failed_traces"] == 1


def test_unparsed_files_never_page(tmp_path):
    spool = tmp_path / "spool"
    spool.mkdir()
    (spool / "garbage.jsonl").write_text("{not json", encoding="utf-8")
    store = TraceStore(tmp_path / "s")
    spy = _Spy()
    watch_spool(store, spool, interval=0.0, max_passes=3,
                webhook_url="http://x/", notify=spy)
    assert spy.bodies == []


def test_dry_run_never_pages(tmp_path):
    spool = tmp_path / "spool"
    spool.mkdir()
    _failing_file(spool, "run.jsonl")
    store = TraceStore(tmp_path / "s")
    spy = _Spy()
    watch_spool(store, spool, interval=0.0, max_passes=3,
                dry_run=True, webhook_url="http://x/", notify=spy)
    assert spy.bodies == []


def test_json_lines_carry_trace_ids(tmp_path, capsys):

    spool = tmp_path / "spool"
    spool.mkdir()
    _failing_file(spool, "run.jsonl")
    store = TraceStore(tmp_path / "s")
    outcome = spool_pass(store, spool)
    assert len(outcome["trace_ids"]) == 1
    loaded = store.load(outcome["trace_ids"][0])
    assert loaded is not None and loaded.success is False
