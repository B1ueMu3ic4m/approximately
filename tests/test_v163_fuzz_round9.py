"""fuzz round 9 — the changelog parser, dedupe bounds, fleet edges.

Targets the newest surfaces: `changelog.parse_plan` on hostile ledger
text (CRLF, nested bold, emoji headings, missing versions, deferred
items), `duplicate_groups` at threshold extremes, and the fleet
detector on degenerate latencies. Contract: sorted reproducible
output or documented skips, never a crash.
"""

import random

from approximately.align import duplicate_groups
from approximately.anomaly import detect_fleet_anomalies
from approximately.changelog import parse_plan
from approximately.recorder import Recorder
from approximately.store import TraceStore

SEED = 20260929
rng = random.Random(SEED)

HOSTILE_PLAN = [
    # normal
    "7. **v0.7 - fine** ✅ (delivered): body.\n",
    # nested bold and emoji title
    "8. **v0.8 - the **bold** and 🚀 title** ✅ (delivered): body\n",
    # no colon, body next line
    "9. **v0.9 - no colon** ✅\nbody here\n",
    # CRLF endings
    "10. **v0.10 - crlf** ✅ (delivered): windows body\r\n",
    # deferred (excluded)
    "11. **v0.11 - later** — **deferred with reasons**\n",
    # missing version number pattern
    "12. **versionless - no v** ✅ (delivered): body\n",
    # huge item number, out of order
    "1. **v99.99 - future** ✅ (delivered): body\n",
    # fullwidth colon
    "13. **v0.13 - fullwidth** ✅ (delivered)：body\n",  # noqa: RUF001
    # empty body
    "14. **v0.14 - empty** ✅ (delivered):\n",
]


def test_changelog_parser_hostile_text(tmp_path):
    plan = tmp_path / "PLAN.md"
    plan.write_text("".join(HOSTILE_PLAN), encoding="utf-8")
    entries = parse_plan(plan)
    versions = [v for v, _, _ in entries]
    # deferred and versionless items stay out; everything else parses
    assert "v0.11" not in versions
    assert "v99.99" in versions and versions[0] == "v99.99"
    assert "v0.10" in versions  # CRLF item survived
    assert "v0.13" in versions  # fullwidth colon survived
    for _, _, body in entries:
        assert isinstance(body, str)


def test_changelog_parser_crlf_file(tmp_path):
    plan = tmp_path / "PLAN.md"
    plan.write_bytes(
        "5. **v0.5 - crlf only** ✅ (delivered): body\r\n".encode())
    entries = parse_plan(plan)
    assert [v for v, _, _ in entries] == ["v0.5"]


def _latency_traces(tmp_path, count, latencies, tool="search"):
    store = TraceStore(tmp_path / f"s{rng.random()}")
    for i in range(count):
        rec = Recorder(f"run {i}", save=False)
        for _j, _ms in enumerate(latencies):
            rec.tool(f"{tool}{_j}", {}, result="ok")
        rec.respond("done", success=True)
        for step, ms in zip(rec.trace.steps, latencies):
            step.latency_ms = ms
        store.save(rec.trace)
    return list(store.list_traces())


def test_fleet_detector_degenerate_latencies(tmp_path):
    cases = [
        [0, 0, 0, 0, 0, 0],            # all zero (untimed)
        [-1, -2, -3, -4, -5, -6],      # negative
        [10**12, 1, 1, 1, 1, 1],       # absurd spike
        [1, 2],                        # under samples
    ]
    for latencies in cases:
        traces = _latency_traces(tmp_path, 1, latencies)
        anomalies = detect_fleet_anomalies(traces)
        assert isinstance(anomalies, list)
        for a in anomalies:
            assert a.robust_z == a.robust_z  # never NaN


def test_duplicate_groups_threshold_extremes(tmp_path):
    traces = []
    store = TraceStore(tmp_path / "s")
    for i in range(5):
        rec = Recorder(f"t {i}", save=False)
        rec.respond("done", success=True)
        store.save(rec.trace)
        traces.append(rec.trace)
    everything = duplicate_groups(traces, threshold=0.0)
    assert everything["groups"] and everything["groups"][0]["size"] == 5
    nothing = duplicate_groups(traces, threshold=1.5)
    assert nothing["groups"] == []
    zero = duplicate_groups(traces, max_traces=0)
    assert zero["groups"] == [] and zero["scanned"] == 0


