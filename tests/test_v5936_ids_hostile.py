"""v5936: the selection feeds pipelines, and the new doors keep
their tempers.

``query --ids`` — one id per line, xargs-friendly: the query DSL
has become the selection primitive for the whole toolkit, so the
answer must pipe. And the week's new surfaces meet hostile input
together: a query expression at the parser's depth/size/pattern
bounds through the memory wrap (refused by name, never a
traceback, on the door and on the wire), a directory named like
a cache entry is not a cache line the prune may unlink, an entry
stamped in the future is kept (not stale is not deleted), and
``0s ago`` is an honest empty window.
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


def _seed(tmp_path):
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    store = TraceStore(tmp_path / "s")
    ids = []
    for i, ok in enumerate((True, False)):
        rec = Recorder(f"pipe run {i}", model="m/1", store=store,
                       save=False)
        rec.tool("deploy", {}, result="ok")
        rec.respond("done", success=ok)
        store.save(rec.trace)
        ids.append(rec.trace.id)
    return ids


def test_ids_is_one_per_line_and_pipes(tmp_path):
    ids = _seed(tmp_path)
    r = _run("--store", str(tmp_path / "s"), "query",
             "success == false", "--ids")
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert lines == [ids[1]], "exactly the failing trace's id"
    r = _run("--store", str(tmp_path / "s"), "query",
             "success == true", "--ids")
    assert r.stdout.splitlines() == [ids[0]]
    r = _run("--store", str(tmp_path / "s"), "query",
             "success == false", "--json")
    assert json.loads(r.stdout)[0]["id"] == ids[1], \
        "the other shapes keep their contracts"


def test_hostile_expressions_refuse_by_name_through_the_memory(tmp_path):
    _seed(tmp_path)
    hostile = ["(" * 60 + "success == false" + ")" * 60,
               "task matches '" + "a" * 300 + "'",
               "x" * 5000]
    for expr in hostile:
        r = _run("--store", str(tmp_path / "s"), "recall",
                 "--query", expr)
        assert r.returncode != 0, expr[:40]
        assert "Traceback" not in r.stderr, expr[:40]
        assert r.stderr.strip(), \
            f"{expr[:40]}: the refusal names itself"
        r = _run("--store", str(tmp_path / "s"), "handoff",
                 "--queue", "3", "--query", expr)
        assert r.returncode != 0 and "Traceback" not in r.stderr


def test_hostile_on_the_wire_is_an_envelope_not_a_crash(tmp_path):
    _seed(tmp_path)
    from approximately.mcp_server import ServerContext, handle_request

    ctx = ServerContext(str(tmp_path / "s"))
    for expr in ("(" * 60 + "success == false" + ")" * 60,
                 "x" * 5000):
        payload = handle_request({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "recall",
                       "arguments": {"query": expr}},
        }, ctx)
        assert payload["result"]["isError"], expr[:40]
        text = payload["result"]["content"][0]["text"]
        assert "Traceback" not in text, \
            "the wire answers with the shape of the refusal"


def test_prune_never_unlinks_a_directory(tmp_path):
    from approximately.doctor import prune_judge_cache

    cache = tmp_path / "jc"
    cache.mkdir()
    dirpath = cache / "dirnamed.json"
    dirpath.mkdir()
    (dirpath / "inside.txt").write_text("payload", encoding="utf-8")
    outcome = prune_judge_cache(cache, 0)
    assert dirpath.is_dir(), \
        "a directory named like an entry is not a cache line"
    assert outcome["pruned"] == 0
    assert all(n != "dirnamed.json" for n in outcome["failed"]), \
        "not a failure either: not an entry at all"


def test_a_future_stamp_is_kept_and_zero_window_is_honest(tmp_path):
    from approximately.doctor import prune_judge_cache
    from approximately.query import parse

    cache = tmp_path / "jc"
    cache.mkdir()
    path = cache / "entry.json"
    path.write_text(json.dumps({"payload": {}, "model": "m"}),
                    encoding="utf-8")
    stamp = time.time() + 3600
    os.utime(path, (stamp, stamp))
    outcome = prune_judge_cache(cache, 7)
    assert outcome == {"pruned": 0, "kept": 1,
                       "freed_bytes": 0, "failed": []}, \
        "not stale is not deleted, even stamped in the future"
    _seed(tmp_path)
    # parse AFTER the seed: the window's "now" must postdate the
    # traces for the zero-window claim to mean anything
    trace_row = parse("created > 0s ago")
    from approximately.store import TraceStore

    traces = TraceStore(tmp_path / "s").list_traces()
    assert not any(trace_row(t) for t in traces), \
        "nothing was created after now: the honest empty window"
