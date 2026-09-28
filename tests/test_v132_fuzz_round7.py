"""v132: fuzz round 7 — the interop surface.

Round 7 targets the import/export pair (v1.19-v1.21): the roundtrip
property (export → import restores id/task/success and is stable
across a second export), hostile-line tolerance on both directions,
and the MCP mirrors.  Contract unchanged: documented errors or clean
skips, never a crash.
"""

import json
import random

import pytest

from approximately.exporter import _FORMATS, export_store
from approximately.importer import _FORMATS as IMPORT_FORMATS
from approximately.importer import import_file, messages_to_steps, sniff_format
from approximately.mcp_server import ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore
from approximately.trace import ERROR, Step

SEED = 20260928
rng = random.Random(SEED)

WEIRD = ["", "\x00", "null", "NaN", "\U0001D4CA\u202E", "x" * 500,
         "q", 0, -1, 1.5, True, None, [], {}, {"k": "v"}]
ROLES = ["user", "assistant", "tool", "system", "developer", "weird"]


def _weird():
    return rng.choice(WEIRD)


def _random_trace(directory, i):
    rec = Recorder(f"task {i} {_weird()}", save=False)
    rec.message("lead", "helper", str(_weird()))
    for _ in range(rng.randint(0, 4)):
        pick = rng.random()
        if pick < 0.35:
            rec.tool(rng.choice(["ls", "cat", "search"]),
                     {"path": _weird()},
                     result=rng.choice(["ok", "", "x" * 300]),
                     error=rng.choice([None, "timeout", "boom"]),
                     agent=rng.choice(["lead", "helper", None]))
        elif pick < 0.55:
            rec.observe(str(_weird()))
        elif pick < 0.75:
            rec.plan(str(_weird()))
        elif pick < 0.9:
            rec.respond(str(_weird()),
                        success=rng.choice([True, False]))
        else:
            rec.trace.add(Step(kind=ERROR, error=str(_weird())))
    rec.respond("final", success=rng.choice([True, False, True]))
    store = TraceStore(directory)
    store.save(rec.trace)
    return rec.trace


def test_roundtrip_identity_and_stability(tmp_path):
    source = TraceStore(tmp_path / "s")
    originals = [_random_trace(source.directory, i) for i in range(40)]
    out = tmp_path / "out.jsonl"
    export_store(source, out)
    fresh = TraceStore(tmp_path / "s2")
    back = import_file(out, fresh)
    assert back["imported"] == 40 and back["skipped"] == 0
    by_id = {t.id: t for t in fresh.list_traces()}
    out2 = tmp_path / "out2.jsonl"
    export_store(fresh, out2)
    for original in originals:
        twin = by_id[original.id]
        assert twin.task == original.task
        assert twin.success == original.success
        # the source store's own on-disk copy must match the
        # in-memory trace save() was given
        reread = source.load(original.id)
        assert reread is not None, f"missing on disk: {original.id}"
        assert reread.task == original.task, (
            f"source disk mangled task for {original.id}: "
            f"{len(original.task)} -> {len(reread.task)} chars")
    # rows must be identical as data, independent of any ordering the
    # filesystem layer chooses
    rows_a = sorted(out.read_text(encoding="utf-8").splitlines())
    rows_b = sorted(out2.read_text(encoding="utf-8").splitlines())
    diff = "\n".join(
        f"{len(a)} vs {len(b)}: {a[-120:]!r} | {b[-120:]!r}"
        for a, b in zip(rows_a, rows_b) if a != b)[:2000]
    assert rows_a == rows_b, diff
    assert out.read_bytes() == out2.read_bytes()


def test_hostile_lines_never_crash(tmp_path):
    payload = "\n".join(json.dumps(g, default=str) if i % 2
                        else repr(g)
                        for i, g in enumerate(WEIRD * 3))
    path = tmp_path / "hostile.jsonl"
    path.write_text(payload + "\n", encoding="utf-8")
    store = TraceStore(tmp_path / "s")
    try:
        result = import_file(path, store)
    except ValueError:
        # a file whose first line is garbage is a documented shape
        # error, not a crash
        result = None
    if result is not None:
        assert result["imported"] + result["skipped"] == result["lines"]
        assert result["lines"] == len(WEIRD) * 3
    # sniffing reports a shape error, not a crash, for every line
    for raw in payload.splitlines():
        single = tmp_path / "one.jsonl"
        single.write_text(raw + "\n", encoding="utf-8")
        try:
            sniff_format(single)
        except ValueError:
            pass


def test_hostile_messages_make_steps_or_skip(tmp_path):
    for _ in range(60):
        messages = [{"role": rng.choice(ROLES),
                     "content": _weird(),
                     "name": _weird(),
                     "is_error": rng.choice([True, False, "yes"]),
                     "tool_call_id": _weird(),
                     "tool_calls": rng.choice([
                         None, [], [{"function": {
                             "name": _weird(),
                             "arguments": rng.choice(
                                 ["{}", "not json", "null"])}}]])}
                    for _ in range(rng.randint(0, 5))]
        steps = messages_to_steps(messages)
        assert all(s.index == i for i, s in enumerate(steps))


def test_unknown_format_and_output_shapes(tmp_path):
    store = TraceStore(tmp_path / "s")
    path = tmp_path / "x.jsonl"
    with pytest.raises(ValueError):
        export_store(store, path, fmt="parquet")
    assert IMPORT_FORMATS == ("native", "openai-jsonl", "messages-list")
    assert set(_FORMATS) == {"openai-jsonl", "native"}


def _call(name, arguments, store_dir):
    ctx = ServerContext(store_dir)
    return handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }, ctx)


def test_mcp_interop_roundtrip(tmp_path):
    source = TraceStore(tmp_path / "s")
    for i in range(10):
        _random_trace(source.directory, i)
    out = tmp_path / "mcp.jsonl"
    exported = _call("export_transcripts",
                     {"output": str(out), "store": str(source.directory)},
                     str(source.directory))
    assert exported["result"]["isError"] is not True
    fresh_dir = tmp_path / "s2"
    imported = _call("import_transcripts",
                     {"path": str(out), "store": str(fresh_dir)},
                     str(fresh_dir))
    assert imported["result"]["isError"] is not True
    counts = json.loads(imported["result"]["content"][0]["text"])
    assert counts["imported"] == 10
    dry = _call("import_transcripts",
                {"path": str(out), "store": str(fresh_dir),
                 "dry_run": True}, str(fresh_dir))
    dry_counts = json.loads(dry["result"]["content"][0]["text"])
    assert dry_counts["imported"] == 0
