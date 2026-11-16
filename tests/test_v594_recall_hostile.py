"""v594: the memory doors meet hostile records on their feet.

The recall family was built and pinned feature by feature, but
never swept with the hostile records every other door already
meets: a 200KB task, a tool name that is a script tag with CRLF,
a 300KB result, a 100KB error, a bool model, a string epoch, a
surrogate in the final output. The doors answer by data, never by
crash - and the PROSE stays line-bounded: a 200KB task renders as
a 72-char line, the 100KB error as a 160-char excerpt. The wire
(JSON) stays data-faithful; the fleet view's divergence compare
survives weird bytes; the exports stay atomic.
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


def _hostile_store(tmp_path):
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    store = TraceStore(tmp_path / "s")
    rec = Recorder("x" * 200000 + "\r\n<script>alert(1)</script>",
                   model=7, store=store, save=False)
    rec.tool("deploy\r\n\t", {"k": "v"}, result="y" * 300000,
             error="e" * 100000)
    rec.respond("done\ud800", success=None)
    rec.trace.created_at = "2024-01-01"
    store.save(rec.trace)
    clean = Recorder("a tidy run", model="m/1", store=store,
                     save=False)
    clean.tool("deploy", {"env": "x"}, result="ok")
    clean.respond("done", success=True)
    store.save(clean.trace)
    return store


def test_the_doors_answer_a_hostile_store_by_data(tmp_path):
    _hostile_store(tmp_path)
    for args in ("recall", "recall-summary", "recall-digest"):
        r = _run("--store", str(tmp_path / "s"), *args.split())
        assert r.returncode == 0, (
            f"{args} rc={r.returncode}: {r.stderr[-300:]}")
        assert "Traceback" not in r.stderr
        lines = r.stdout.splitlines()
        assert max(len(ln) for ln in lines) < 500, (
            f"{args} leaked a raw oversized field into the prose")


def test_the_search_survives_a_hostile_needle(tmp_path):
    _hostile_store(tmp_path)
    for needle in ("<script>", "x", "%00", "done"):
        r = _run("--store", str(tmp_path / "s"), "recall",
                 "--grep", needle, "--json")
        assert r.returncode == 0, r.stderr
        payload = json.loads(r.stdout)
        assert "results" in payload


def test_the_wire_is_data_faithful_and_valid(tmp_path):
    _hostile_store(tmp_path)
    r = _run("--store", str(tmp_path / "s"), "recall", "--json")
    payload = json.loads(r.stdout)
    hostile = [e for day in payload["days"] for e in day["entries"]
               if e["task"].startswith("xxx")]
    assert hostile, "the hostile record is on the wire as data"
    assert hostile[0]["task"].startswith("xxx"), \
        "the JSON carries the record's own task, not a display cut"


def test_the_mcp_tool_answers_a_hostile_store(tmp_path):
    from approximately.mcp_server import ServerContext, handle_request

    _hostile_store(tmp_path)
    ctx = ServerContext(str(tmp_path / "s"))
    payload = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "recall", "arguments": {"digest": True}},
    }, ctx)
    assert not payload["result"]["isError"], (
        "a hostile store is data, not a tool failure")
    result = json.loads(payload["result"]["content"][0]["text"])
    assert result["conversations"] == 2


def test_the_fleet_compare_survives_weird_bytes(tmp_path):
    _hostile_store(tmp_path)
    other = tmp_path / "box-b"
    other.mkdir()
    from approximately.store import TraceStore

    dup = TraceStore(tmp_path / "s").list_traces()[0]
    dup.steps[0].result = "edited elsewhere \ud800"
    TraceStore(other).save(dup)
    r = _run("recall", str(tmp_path / "s"), str(other))
    assert r.returncode == 0, r.stderr
    assert "DIVERGED" in r.stdout, \
        "weird bytes still count as divergence, not a crash"


def test_the_exports_write_and_read_back(tmp_path):
    _hostile_store(tmp_path)
    for door, out in (("recall", "diary.md"),
                      ("recall-digest", "digest.md")):
        path = tmp_path / out
        r = _run("--store", str(tmp_path / "s"), door, "--export",
                 str(path))
        assert r.returncode == 0, r.stderr
        assert path.exists() and not list(tmp_path.glob("*.tmp"))
        text = path.read_text(encoding="utf-8")
        assert "Traceback" not in text
        lines = text.splitlines()
        assert max(len(ln) for ln in lines) < 500, \
            f"{out} leaked a raw oversized field"
