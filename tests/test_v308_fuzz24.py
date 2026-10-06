"""v308: fuzz 24 — chaos for the v3 surfaces.

The nightly audit's week_compare, the ops resources, the audit's
grade floor and price-catalog finding, the evidence pack's agent
grade — each attacked with foreign records, hand-edited digests and
degenerate values. Contract: documented errors or honest
unusable/None, never a crash that escapes as a protocol fault.
"""

import datetime
import json

import pytest

from approximately.evidence import build_evidence_pack
from approximately.fleet import summarize_trend, week_compare
from approximately.grade import below_floor
from approximately.mcp_server import ServerContext, _resources, _resources_read, _tool_audit
from approximately.prices import validate_table
from approximately.recorder import Recorder
from approximately.store import TraceStore


def test_week_compare_vs_poison_days():
    # corrupt day labels, missing fields, negative values, future
    # rows, duplicate days: the buckets count what parses
    rows = [
        {"day": "not-a-date", "failures": 1, "est_spend": 1.0},
        {"day": "2026-10-05"},  # no failures, no spend
        {"day": "2026-10-06", "failures": -5, "est_spend": -1.0},
        {"day": "2026-10-06", "failures": 2, "est_spend": 3.0},
        {"day": "2999-01-01", "failures": 99, "est_spend": 9.0},
    ]
    r = week_compare(rows, today=datetime.date(2026, 10, 6))
    # the bad day label drops out of the buckets; the 10-05 row
    # lands in LAST week (ISO Monday), the two 10-06 rows in this
    # 10-05 is this week's ISO Monday, so the no-fields row rides
    # in this week too: 3 rows, -5 + 2 + 0 = -3 as given (the
    # compare is a mirror, not a lie fixer); last week is empty
    assert r["usable"] is False
    assert r["this_week"]["failures"] == -3
    assert r["this_week"]["days"] == 3
    assert r["last_week"]["days"] == 0
    assert r["deltas"]["failures"] is None


def test_week_compare_vs_bad_row_shapes():
    # digest rows are untrusted: a row with no day, or a day that
    # does not parse, drops out - unusable, never a crash
    assert week_compare([{"failures": 1}])["usable"] is False
    assert week_compare([{"day": 12345}])["usable"] is False
    r = week_compare([{"day": str(datetime.date.today()),
                       "failures": 0, "est_spend": 0.0}])
    assert r["usable"] is False  # one week populated is not a compare
    assert r["this_week"]["days"] == 1
    assert r["deltas"]["est_spend"] is None


def test_summarize_trend_vs_duplicate_days():
    # summarize_trend mirrors rows 1:1 (the merge lives in
    # trend_days, at the file level); a duplicated day rides in
    # twice and week_compare sums it as given
    days = [{"day": "2026-10-05", "snapshots": 1,
             "last": {"failures": 1, "est_spend": 1.0,
                      "stores": [{"traces": 3, "failures": 1,
                                  "est_spend": 1.0}]}}]
    r = summarize_trend(days + days)
    assert len(r["days"]) == 2
    wc = week_compare(r["days"],
                      today=datetime.date(2026, 10, 6))
    # 10-05 IS this week's Monday: both rows land this week
    assert wc["this_week"]["failures"] == 2
    assert wc["last_week"]["days"] == 0


def test_ops_resources_vs_empty_store(tmp_path):
    TraceStore(tmp_path)
    ctx = ServerContext(str(tmp_path))
    uris = [r["uri"] for r in _resources(ctx)]
    assert any(u.endswith("/grades") for u in uris)
    grades = _resources_read(
        {"params": {"uri": f"approximately://{tmp_path}/grades"}},
        ctx, 1)
    payload = json.loads(grades["result"]["contents"][0]["text"])
    assert payload["grades"] == []
    tri = _resources_read(
        {"params": {"uri": f"approximately://{tmp_path}/triage"}},
        ctx, 2)
    assert json.loads(tri["result"]["contents"][0]["text"])["total"] == 0


def test_audit_floor_all_na_and_single_trace(tmp_path):
    store = TraceStore(tmp_path)
    with Recorder("only run", store=store) as rec:
        rec.tool("sh", {}, result="ok")
    rep = _tool_audit(ServerContext(str(tmp_path)),
                      {"grade_floor": "A"})
    # one trace grades n/a and n/a never fails an audit
    assert rep["ok"] is True
    assert rep["grades"]["below"] == []
    from approximately.mcp_server import _tool_grade

    with pytest.raises(KeyError, match="no agent"):
        _tool_grade(ServerContext(str(tmp_path)),
                    {"subject": "ghost"})


def test_below_floor_vs_garbage_letters():
    rows = [{"subject": "x", "grade": "Z"}]
    assert below_floor(rows, "B") == []  # unknown grades never match
    with pytest.raises(ValueError, match="grade floor"):
        below_floor([], "1")


def test_evidence_grade_vs_unattributed(tmp_path):
    store = TraceStore(tmp_path)
    with Recorder("no agent anywhere", store=store) as rec:
        rec.tool("sh", {}, result="ok")
        rec.fail("boom")
    out = tmp_path / "case.zip"
    manifest = build_evidence_pack(
        store, next(t.id for t in store.list_traces()), out)
    assert manifest["agent_grade"] is None


def test_prices_vs_giant_table_and_weird_keys(tmp_path):
    from approximately.prices import set_rate

    big = {f"model-{i}": float(i) for i in range(2_000)}
    for name, rate in big.items():
        set_rate(tmp_path, name, rate)
    from approximately.prices import load_catalog

    got = load_catalog(tmp_path)
    assert len(got) == 2_000
    with pytest.raises(ValueError, match="bad model name"):
        validate_table({"a\nb": 1.0})
    with pytest.raises(ValueError, match="bad model name"):
        validate_table({None: 1.0})


def test_snapshot_vs_rapid_succession(tmp_path):
    from approximately.snapshot import restore, snapshot

    store = TraceStore(tmp_path / "s")
    with Recorder("run", store=store) as rec:
        rec.tool("sh", {}, result="ok")
    out = tmp_path / "a.zip"
    snapshot(tmp_path / "s", out)
    r1 = restore(out, tmp_path / "r1")
    r2 = restore(out, tmp_path / "r2", force=True)
    assert r1["members"] == r2["members"] >= 1
