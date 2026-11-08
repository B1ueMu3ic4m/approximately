"""v386: trace ids are names, not paths.

The store's save wrote ``directory/<id>.json`` with no fence:
a hostile trace id (``../../tmp/evil``) shipped in as a
trace_ship row — and imported with the operator's override —
turned the receiving box's store into an arbitrary-write
primitive. Save now refuses anything that is not one safe
token; the explicit-path LOAD feature (the caller names the
file, like cat) keeps working, climbs refused; and the import
door marks a shipment whose id is not a name as malformed at
plan time — the poison never reaches the apply loop.
"""

import json
import tempfile

import pytest

from approximately.cli import cmd_inbox_import
from approximately.store import TraceStore, _safe_id
from approximately.trace import Trace


def test_save_refuses_ids_that_are_paths(tmp_path):
    store = TraceStore(tmp_path)
    for hostile in ("../evil", "sub/dir", "/abs/path",
                    ".hidden", "..", "a/b/c"):
        trace = Trace(task="x", id=hostile)
        with pytest.raises(ValueError, match="not a safe name"):
            store.save(trace, stamp=False)


def test_save_still_accepts_the_usual_ids(tmp_path):
    store = TraceStore(tmp_path)
    for good in ("a7fd5a15e059", "abc123", "a.b_c-d", "x.json"):
        trace = Trace(task="x", id=good)
        store.save(trace, stamp=False)
    assert len(store.list_traces()) == 4


def test_load_resolves_inside_the_fence_only(tmp_path):
    store = TraceStore(tmp_path)
    assert store.load("../outside") is None
    assert store.load("/etc/passwd") is None
    assert store.load("sub/thing") is None


def test_load_still_honors_explicit_files(tmp_path):
    store = TraceStore(tmp_path)
    trace = Trace(task="elsewhere", id="abc123def456")
    explicit = tmp_path / "elsewhere.json"
    explicit.write_text(trace.to_json(), encoding="utf-8")
    loaded = store.load(str(explicit))
    assert loaded is not None and loaded.id == trace.id
    # and the extension-less shape the CLI doors accept
    loaded2 = store.load(str(tmp_path / "elsewhere"))
    assert loaded2 is not None and loaded2.id == trace.id
    # climbs stay refused even for explicit paths
    assert store.load(f"{tmp_path}/../{tmp_path.name}/e.json") \
        is None


def _ship_row(trace_dict, verified=True, at=1.0):
    return {"received_at": at, "verified": verified,
            "kind": "trace_ship", "payload": {"trace": trace_dict}}


def test_import_marks_hostile_ids_malformed_at_plan_time():
    receiver = TraceStore(tempfile.mkdtemp())
    archive = receiver.directory / "webhook-log.jsonl"
    good = {"id": "a7fd5a15e059", "task": "fine", "steps": []}
    evil = {"id": "../../tmp/evil", "task": "the write", "steps": []}
    with archive.open("a", encoding="utf-8") as fh:
        for trace in (good, evil):
            fh.write(json.dumps(_ship_row(trace),
                                sort_keys=True) + "\n")
    # plan: the poison is named, not hidden
    import argparse
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cmd_inbox_import(argparse.Namespace(
            store=str(receiver.directory), archive=None,
            apply=False, allow_unverified=False,
            include_rotated=False, json=True, trace=None,
            url=None, key_file=None))
    plan = json.loads(buf.getvalue())
    assert plan["importable"] == 1 and plan["malformed"] == 1

    # apply: the poison never reaches the store
    cmd_inbox_import(argparse.Namespace(
        store=str(receiver.directory), archive=None,
        apply=True, allow_unverified=True, confirm=True,
        include_rotated=False, json=False, trace=None,
        url=None, key_file=None))
    ids = [t.id for t in receiver.list_traces()]
    assert ids == ["a7fd5a15e059"], \
        "the write-shaped id never became a filename"


def test_safe_id_the_predicate():
    assert _safe_id("a7fd5a15e059")
    assert _safe_id("a.b_c-d")
    assert _safe_id("x.json")
    assert not _safe_id("../evil")
    assert not _safe_id("a/b")
    assert not _safe_id("/abs")
    assert not _safe_id(".hidden")
    assert not _safe_id("")
    assert not _safe_id("a b")
