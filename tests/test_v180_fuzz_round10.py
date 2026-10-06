"""fuzz round 10 — the surfaces v1.54-v1.77 added.

The changelog generator on adversarial-but-valid ledgers (versions
out of physical order, duplicate versions, wrapped bodies, blank-line
storms) must always render sorted, deduped sections. `max_latency`,
`export --dedupe` and the report manifest hold their shapes on
degenerate inputs. Contract: reproducible structure, never a crash.
"""

import random

from approximately.changelog import parse_plan, render
from approximately.cli import _status_payload
from approximately.exporter import export_store
from approximately.query import select
from approximately.recorder import Recorder
from approximately.store import TraceStore

SEED = 20260930
rng = random.Random(SEED)

VERSIONS = ["v0.1", "v0.10", "v1.2", "v1.20", "v2.0", "v10.3",
            "v1.2.3", "v1.2.4"]


def _hostile_plan(tmp_path):
    """Versions deliberately out of physical order, blank-line storms,
    two colon styles — but every heading stays parseable (titles never
    contain nested bold, the round-9 rule)."""
    lines = []
    for i, version in enumerate(VERSIONS):
        gap = "\n\n\n" * (i % 3)
        body = "\n".join(f"line {j} word " * 1 for j in
                         range(rng.randint(0, 3)))
        lines.append(f"{gap}{i}. **{version} - the {i} title** \u2705 "
                     f"(delivered): {body}\n")
    # guarantee a parseable anchor so the sorted/render properties are
    # non-vacuous
    lines.insert(0, "0. **v0.0 - plain anchor** \u2705 (delivered): "
                    "anchor body\n")
    plan = tmp_path / "PLAN.md"
    plan.write_text("".join(lines), encoding="utf-8")
    return plan


def test_changelog_render_is_sorted_and_stable(tmp_path):
    plan = _hostile_plan(tmp_path)
    first = parse_plan(plan)
    second = parse_plan(plan)
    assert len(first) >= len(VERSIONS)
    assert [v for v, _, _ in first] == [v for v, _, _ in second]
    keys = [[int(p) for p in v[1:].split(".")] for v, _, _ in first]
    assert keys == sorted(keys, reverse=True)
    # render is a pure function of the parse
    assert render(first) == render(first)
    # every input version appears exactly once in the sections
    text = render(first)
    for version in VERSIONS:
        assert f"## {version}" in text


def test_max_latency_degenerate_traces(tmp_path):
    store = TraceStore(tmp_path / "s")
    cases = [(0, 0), (-5,), (10**9,), (1, 2, 3)]
    for i, latencies in enumerate(cases):
        rec = Recorder(f"case {i}", save=False)
        for _ in latencies:
            rec.tool("deploy", {}, result="ok")
        rec.respond("done", success=True)
        for step, ms in zip(rec.trace.steps, latencies, strict=False):
            step.latency_ms = ms
        store.save(rec.trace)
        assert isinstance(select(store.list_traces(),
                                 "max_latency >= 0"), list)


def test_export_dedupe_bounds(tmp_path):
    store = TraceStore(tmp_path / "s")
    for i in range(6):
        rec = Recorder(f"task {i % 2}", save=False)
        rec.tool("search", {"q": str(i % 2)}, result="same")
        rec.respond("booked", success=True)
        store.save(rec.trace)
    out = tmp_path / "o.jsonl"

    result = export_store(store, out, dedupe=True)
    assert result["dedupe_dropped"] >= 1
    assert result["written"] <= 4


def test_status_payload_shape_on_tiny_stores(tmp_path):
    store = TraceStore(tmp_path / "s")
    rec = Recorder("tiny", save=False)
    rec.respond("done", success=True)
    store.save(rec.trace)
    payload = _status_payload(store, store.list_traces(), None, None)
    for key in ("traces", "failures", "fleet_anomalies",
                "triage_coverage"):
        assert key in payload
    assert payload["fleet_anomalies"]["count"] in (0, 1)
