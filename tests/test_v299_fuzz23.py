"""v299: fuzz 23 — chaos for the night's six new surfaces.

Every prior fuzz round found at least one real lie. This one attacks
redact, triage, prices, grade, handoff and snapshot with foreign
records, hand-edited fields, degenerate values and hostile shapes.
Found this round: a string ``created_at`` (hand-edited or imported)
crashed triage's min/max and handoff's localtime — ``coerce_epoch``
now gates both, zeroing poison instead of dying.
"""

import json

import pytest

from approximately.handoff import brief
from approximately.mcp_server import ServerContext, _tool_snapshot
from approximately.prices import set_rate, validate_table
from approximately.redact import compile_patterns, redact_trace
from approximately.snapshot import snapshot
from approximately.store import TraceStore
from approximately.trace import Step, Trace, coerce_epoch
from approximately.triage import triage_store


def _failed_trace(store, task="run"):
    t = Trace(task=task, model="m")
    t.add(Step(kind="tool_call", tool="sh", result="x",
               tokens=100, latency_ms=5))
    t.success = False
    store.save(t)
    return t


def _poison_on_disk(store, trace, **fields):
    """Rewrite fields on disk the way a foreign importer would."""
    path = store.directory / f"{trace.id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(fields)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_string_created_at_survives_everything(tmp_path):
    store = TraceStore(tmp_path)
    _failed_trace(store, "string time")
    _failed_trace(store, "float time")
    t1 = store.list_traces()[0]
    _poison_on_disk(store, t1, created_at="1730000000")
    rows = triage_store(store)
    assert len(rows) == 2  # zeroed timestamp sorts oldest, no crash
    page = brief(store.load(t1.id), store)  # handoff too
    assert "outcome: FAILED" in page


def test_null_and_bool_created_at(tmp_path):
    store = TraceStore(tmp_path)
    t = _failed_trace(store, "null time")
    _poison_on_disk(store, t, created_at=None)
    assert triage_store(store)
    _poison_on_disk(store, t, created_at=True)
    rows = triage_store(store)
    assert rows[0].recency_norm == 0.0
    assert coerce_epoch(None) == 0.0
    assert coerce_epoch(True) == 0.0
    assert coerce_epoch(False) == 0.0
    assert coerce_epoch(1.5) == 1.5
    assert coerce_epoch("12") == 0.0


def test_redact_vs_degenerate_and_overlapping(tmp_path):
    store = TraceStore(tmp_path)
    t = _failed_trace(store, "degenerate")
    t.final_output = None
    t.steps[0].args = {"nested": {"deep": ["sk-abcdefghijklmnopqrst",
                                            42, None, ["x"]]}}
    t.steps[0].thought = None
    t.steps[0].error = None
    share, report = redact_trace(t)
    assert report["hits"].get("openai_key") == 1
    assert share.steps[0].args["nested"]["deep"][1] == 42
    assert share.steps[0].args["nested"]["deep"][2] is None
    # empty and huge inputs complete
    empty = Trace(task="", model="m")
    rep2 = redact_trace(empty)[1]
    assert rep2["total"] == 0
    huge = Trace(task="k" * 50_000, model="m")
    redact_trace(huge)  # completes; the scrubber is linear
    # arg KEYS are never rewritten (documented behavior)
    keyed = Trace(task="k", model="m")
    keyed.add(Step(kind="tool_call", tool="sh",
                   args={"sk-abcdefghijklmnopqrst": "value"}))
    share3, rep3 = redact_trace(keyed)
    assert "sk-abcdefghijklmnopqrst" in share3.steps[0].args
    assert rep3["total"] == 0


def test_redact_user_pattern_boundaries():
    # Pattern shape is operator-reviewed: Python re has no timeout,
    # so compile_patterns refuses syntax errors only, and a
    # catastrophic custom pattern is self-inflicted (documented in
    # SECURITY.md). What the door promises: a valid LINEAR pattern
    # compiles, runs, and reports its hits.
    table = compile_patterns(extra=["badge=badge-[0-9]{4,}"])
    hits = {}
    from approximately.redact import _scrub

    out = _scrub("badge-12345 and badge-9", table, hits)
    assert hits.get("badge") == 1  # {4,} needs 4 digits
    assert "[REDACTED:badge]" in out
    with pytest.raises(ValueError):
        compile_patterns(extra=["broken=(unclosed"])


def test_prices_hostile_but_finite(tmp_path):
    set_rate(tmp_path, "huge", 1e300)
    set_rate(tmp_path, "tiny", 1e-300)
    from approximately.prices import load_catalog

    got = load_catalog(tmp_path)
    assert got["huge"] == 1e300 and got["tiny"] == 1e-300
    with pytest.raises(ValueError):
        validate_table({"m": float("inf")})
    with pytest.raises(ValueError):
        validate_table({"m": float("-inf")})
    # duplicate JSON keys: last wins (documented json behavior)
    (tmp_path / "prices.json").write_text(
        '{"a": 1.0, "a": 2.0}', encoding="utf-8")
    assert load_catalog(tmp_path) == {"a": 2.0}


def test_grade_vs_degenerate_scorecards():
    from approximately.grade import grade_card

    # hand-edited negative counts never produce a negative grade
    row = grade_card({"agent": "z", "traces": 5,
                      "failure_rate": -0.5, "errors": -3,
                      "tool_calls": 10, "breached_traces": -1})
    assert row["budget"] == "A"  # no breach evidence is not a breach
    assert row["reliability"] == "A"  # clamped, not rewarded further
    empty = grade_card({"agent": "e", "traces": 0})
    assert empty["grade"] == "n/a"


def test_handoff_vs_null_fields(tmp_path):
    store = TraceStore(tmp_path)
    t = _failed_trace(store, "nulls")
    _poison_on_disk(store, t, task=None, model=None,
                    final_output=None, success=None)
    page = brief(store.load(t.id), store)
    assert "# Handoff:" in page
    assert "outcome: unknown" in page


def test_snapshot_vs_empty_and_unicode_members(tmp_path):
    store = TraceStore(tmp_path)
    _failed_trace(store, "零 day ⌘")
    (tmp_path / "empty.json").write_text("", encoding="utf-8")
    out = tmp_path / "snap.zip"
    rep = snapshot(tmp_path, out)
    assert rep["members"] >= 2  # trace + the empty root json
    from approximately.snapshot import restore

    r = restore(out, tmp_path / "into")
    assert r["members"] == rep["members"]
    # the empty file rides along; list_traces skips it loudly
    store2 = TraceStore(tmp_path / "into")
    assert len(store2.list_traces()) == 1


def test_snapshot_of_empty_store_roundtrips(tmp_path):
    # TraceStore creates missing dirs: an empty store snapshots to
    # zero members and restores to an empty store, no crash
    rep = _tool_snapshot(ServerContext(str(tmp_path)),
                         {"path": str(tmp_path / "x.zip")})
    assert rep["members"] == 0
    from approximately.snapshot import restore

    r = restore(tmp_path / "x.zip", tmp_path / "into")
    assert r["members"] == 0


def test_mcp_tool_snapshot_store_arg(tmp_path):
    src = tmp_path / "store"
    store = TraceStore(src)
    _failed_trace(store)
    rep = _tool_snapshot(ServerContext(str(tmp_path)),
                         {"store": str(src),
                          "path": str(tmp_path / "s.zip")})
    assert rep["members"] >= 1
