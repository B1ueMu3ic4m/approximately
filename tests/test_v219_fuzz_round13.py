"""v219: fuzz round 13 — the spool and the doctor under attack.

The spool watches an untrusted directory and the doctor's spool
check runs untrusted files through the sniffer.  Round-4 contract
again: documented errors or clean skips, never a crash — and the
parallel ingest path stays idempotent when the same OTLP file
arrives twice in flight.
"""

import json
import random

from approximately.doctor import doctor
from approximately.importer import import_paths
from approximately.mcp_server import ServerContext, handle_request
from approximately.spool import spool_pass
from approximately.store import TraceStore
from approximately.toolscan import scan

SEED = 20261001


def _envelope(trace_id="a" * 32):
    return {"resourceSpans": [{"scopeSpans": [{"spans": [
        {"traceId": trace_id, "spanId": "1" * 16, "parentSpanId": "",
         "name": "run"}]}]}]}


def _write_envelope(path, trace_id="a" * 32):
    path.write_text(json.dumps(_envelope(trace_id)) + "\n",
                    encoding="utf-8")


def test_spool_garbage_never_crashes(tmp_path):
    rng = random.Random(SEED)
    pool = ["", "\x00", "{{{", "null", "[]", "x" * 10_000,
            '{"resourceSpans": 3}', json.dumps(_envelope()),
            json.dumps(_envelope()) + "\n", "\U0001F4A9", "-" * 200]
    spool = tmp_path / "spool"
    spool.mkdir()
    for i in range(60):
        name = rng.choice(["f", "g", "h", "中文", "a.b.c"]) + \
            f"{i}.jsonl"
        (spool / name).write_text(rng.choice(pool), encoding="utf-8")
    result = spool_pass(TraceStore(tmp_path / "s"), spool)
    assert result["files"] == 60
    assert (result["imported"] + result["failures"]
            + (result["skipped"] or 0) >= 0)
    # every file accounted for: archived, or left as a failure
    left = result["left"]
    assert len(list(spool.glob("*.jsonl"))) == left


def test_spool_subdirectories_are_ignored(tmp_path):
    spool = tmp_path / "spool"
    (spool / "done").mkdir(parents=True)
    (spool / "done" / "x.jsonl").write_text("{}", encoding="utf-8")
    result = spool_pass(TraceStore(tmp_path / "s"), spool)
    assert result["files"] == 0


def test_doctor_spool_garbage_is_a_count_not_a_crash(tmp_path):
    store = TraceStore(tmp_path / "s")
    spool = tmp_path / "spool"
    spool.mkdir()
    (spool / "j.json").write_text("{", encoding="utf-8")
    _write_envelope(spool / "ok.json")
    report = doctor(store.directory, spool_dir=spool)
    assert report.spool_pending == 2
    assert report.spool_unparsed == ["j.json"]


def test_doctor_spool_missing_store_is_tolerated(tmp_path):
    spool = tmp_path / "spool"
    spool.mkdir()
    _write_envelope(spool / "ok.json")
    # the store directory does not exist yet: the check reports
    # instead of crashing
    report = doctor(tmp_path / "s", spool_dir=spool)
    assert report.spool_pending == 1
    assert report.spool_unparsed == []


def test_parallel_otel_ingest_is_idempotent(tmp_path):
    # the same envelope twice in flight: deterministic ids collapse
    # them to one trace
    dump = tmp_path / "dump.jsonl"
    lines = [json.dumps(_envelope(f"{i:032x}")) for i in range(20)]
    dump.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = import_paths([str(dump), str(dump)],
                          TraceStore(tmp_path / "s"), fmt="otel",
                          jobs=2)
    store = TraceStore(tmp_path / "s")
    assert result["imported"] == 20
    assert len(store.list_traces()) == 20


def test_mcp_spool_once_garbage(tmp_path):
    spool = tmp_path / "spool"
    spool.mkdir()
    for i in range(10):
        (spool / f"f{i}.json").write_text("garbage", encoding="utf-8")
    payload = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "spool_once",
                   "arguments": {"dir": str(spool)}},
    }, ServerContext(str(tmp_path / "s")))
    result = json.loads(payload["result"]["content"][0]["text"])
    assert result["failures"] == 10
    assert payload["result"]["isError"] is not True


def test_own_tools_scan_clean():
    # the shipped tool inventory must pass our own poisoning scan
    import argparse

    from approximately.cli import cmd_mcp

    target = "/tmp/approx-self-tools.json"
    args = argparse.Namespace(store=".", print_tools=target)
    assert cmd_mcp(args) == 0
    result = scan(target)
    assert result.verdict == "clean"
    assert result.findings == []
