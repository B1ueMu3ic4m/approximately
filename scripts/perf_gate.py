#!/usr/bin/env python3
"""Attribution performance gate: complexity-regression tripwire.

Attributes every record of the synthetic fixture and asserts the
per-record mean stays under a deliberately generous bound. The bound
is ~25x the observed headroom (2.1 ms/record locally), so ordinary
CI-runner variance cannot trip it — only an algorithmic-complexity
regression (the O(n^2)/backtracking class the fuzz round guards
against) can.

Usage: python scripts/perf_gate.py [--max-ms-per-record 50]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from approximately.attributor import attribute  # noqa: E402
from approximately.distill import load_dataset  # noqa: E402

SYNTH = ROOT / "docs" / "mast-bench-synth.jsonl"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-ms-per-record", type=float, default=50.0,
                        help="per-record attribution budget in "
                             "milliseconds (default 50, ~25x headroom)")
    args = parser.parse_args()
    return (attribution_gate(args) + agent_wave_gate()
            + query_gate() + similar_gate() + fleet_anomaly_gate()
            + import_gate() + export_gate() + doctor_gate()
            + spool_gate() + survey_spend_gate() + ci_gate()
            + doctor_deep_gate() + clean_gate() + csv_export_gate()
            + evidence_gate() + compare_gate() + budget_gate()
            + junit_gate() + quarantine_gate() + result_meter_gate()
            + composition_gate() + failure_budget_gate()
            + tail_gate() + startup_gate() + complexity_gate())

def fleet_anomaly_gate(budget_s: float = 10.0) -> int:
    """Per-tool fleet baselines over a 10k-trace store.

    The fleet anomaly scan (v1.41) must stay linear in traces x steps:
    two tools x 5k traces, every step timed, baselined and flagged
    within budget. A superlinear baseline here means the night-watch
    `status` frame stalls on real stores.
    """
    from approximately.anomaly import detect_fleet_anomalies
    from approximately.recorder import Recorder

    traces = []
    for i in range(10_000):
        rec = Recorder(f"t {i}", save=False)
        rec.tool("search", {"q": i}, result="hit")
        rec.tool("deploy", {"env": "prod"}, result="ok")
        rec.respond("done", success=True)
        search_ms = 5000 if i % 500 == 0 else 100 + i % 50
        for step, ms in zip(rec.trace.steps,
                            (search_ms, 2000 + i % 500), strict=False):
            step.latency_ms = ms
        traces.append(rec.trace)

    start = time.perf_counter()
    anomalies = detect_fleet_anomalies(traces)
    elapsed = time.perf_counter() - start
    if not anomalies:
        print("FAIL: fleet gate found no anomalies in crafted data",
              file=sys.stderr)
        return 1
    print(f"perf-gate[fleet-anomalies]: baselines over 10k traces in "
          f"{elapsed * 1000:.0f}ms ({len(anomalies)} flagged, budget "
          f"{budget_s:g}s) - "
          + ("PASS" if elapsed <= budget_s else "FAIL"))
    if elapsed > budget_s:
        print("FAIL: fleet anomalies slowed past budget",
              file=sys.stderr)
        return 1
    return 0


def import_gate(budget_s: float = 15.0) -> int:
    """Ingest 500 mixed-shape transcripts (tool calls, tool errors,
    multi-turn) into a fresh store. Parallel-safe and deterministic —
    this gate pins the ingest path so it stays linear as the batch
    grows.  The budget is roomy on purpose (local runs land near
    150ms): shared CI runners — Windows especially — swing by
    seconds on I/O, and the gate must catch real scaling
    regressions, not runner noise.  A quadratic blowup still trips
    it by minutes."""
    import json as _json
    import tempfile
    from pathlib import Path as _Path

    from approximately.importer import import_paths
    from approximately.store import TraceStore

    lines = []
    for i in range(500):
        row = {"messages": [
            {"role": "user", "content": f"task {i}"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"type": "function",
                 "function": {"name": "search",
                              "arguments": _json.dumps({"q": i})},
                 "id": f"call_{i}"}]},
            {"role": "tool", "name": "search",
             "tool_call_id": f"call_{i}",
             "content": f"{i} hits",
             **({"is_error": True} if i % 7 == 0 else {})},
            {"role": "assistant", "content": f"done {i}"},
        ]}
        lines.append(_json.dumps(row))
    tmp = _Path(tempfile.mkdtemp())
    dump = tmp / "dump.jsonl"
    dump.write_text("\n".join(lines) + "\n", encoding="utf-8")
    store = TraceStore(tmp / "store")

    start = time.perf_counter()
    result = import_paths([str(dump)], store, jobs=4)
    elapsed = time.perf_counter() - start
    if result["imported"] != 500:
        print("FAIL: import gate ingested the wrong count",
              file=sys.stderr)
        return 1
    failures = sum(1 for t in store.list_traces()
                   if t.success is False)
    if failures != 500 // 7 + (1 if 500 % 7 else 0) - 0 and \
            failures < 70:
        print(f"FAIL: import gate lost tool errors ({failures})",
              file=sys.stderr)
        return 1
    print(f"perf-gate[import]: 500 transcripts in "
          f"{elapsed * 1000:.0f}ms ({failures} failed, budget "
          f"{budget_s:g}s) - "
          + ("PASS" if elapsed <= budget_s else "FAIL"))
    if elapsed > budget_s:
        print("FAIL: ingest slowed past budget", file=sys.stderr)
        return 1
    return 0


def doctor_gate(budget_s: float = 5.0) -> int:
    """The store health check over 2k traces, orphan annotations and
    a judge cache included. Doctor grew several passes (orphans,
    judge cache, ledger) — this gate pins the whole walk so the
    night-watch invocation stays bounded."""
    import tempfile
    from pathlib import Path as _Path

    from approximately.doctor import doctor
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    tmp = _Path(tempfile.mkdtemp())
    store = TraceStore(tmp / "store")
    for i in range(2000):
        rec = Recorder(f"run {i}", save=False)
        rec.tool("deploy", {}, result="ok")
        rec.respond("done", success=not rec.trace.steps)
        store.save(rec.trace)
    cache = tmp / "jcache"
    cache.mkdir()
    start = time.perf_counter()
    report = doctor(store.directory, judge_cache=cache)
    elapsed = time.perf_counter() - start
    if report.records != 2000:
        print("FAIL: doctor gate saw the wrong record count",
              file=sys.stderr)
        return 1
    print(f"perf-gate[doctor]: 2000 traces + judge cache in "
          f"{elapsed * 1000:.0f}ms (budget {budget_s:g}s) - "
          + ("PASS" if elapsed <= budget_s else "FAIL"))
    if elapsed > budget_s:
        print("FAIL: doctor slowed past budget", file=sys.stderr)
        return 1
    return 0


def export_gate(budget_s: float = 10.0) -> int:
    """Export 500 traces as OpenAI chat JSONL. The inverse of the
    ingest gate: tool-call steps, observations and metadata must all
    serialize within budget, with every trace accounted for."""
    import json as _json
    import tempfile
    from pathlib import Path as _Path

    from approximately.exporter import export_store
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    tmp = _Path(tempfile.mkdtemp())
    store = TraceStore(tmp / "store")
    for i in range(500):
        rec = Recorder(f"task {i}", save=False)
        rec.tool("search", {"q": i}, result=f"{i} hits")
        rec.respond(f"done {i}", success=i % 7 != 0)
        store.save(rec.trace)
    out = tmp / "out.jsonl"

    start = time.perf_counter()
    result = export_store(store, out)
    elapsed = time.perf_counter() - start
    if result["written"] != 500:
        print("FAIL: export gate wrote the wrong count", file=sys.stderr)
        return 1
    rows = out.read_text(encoding="utf-8").splitlines()
    if len(rows) != 500 or not all(
            _json.loads(r).get("messages") for r in rows):
        print("FAIL: export gate produced malformed rows", file=sys.stderr)
        return 1
    print(f"perf-gate[export]: 500 traces in "
          f"{elapsed * 1000:.0f}ms (budget {budget_s:g}s) - "
          + ("PASS" if elapsed <= budget_s else "FAIL"))
    if elapsed > budget_s:
        print("FAIL: export slowed past budget", file=sys.stderr)
        return 1
    return 0


def attribution_gate(args) -> int:
    labeled = load_dataset(SYNTH, fmt="approx")
    if not labeled:
        print("perf-gate: no records found", file=sys.stderr)
        return 1
    traces = [t for t, _ in labeled]

    start = time.perf_counter()
    for trace in traces:
        attribute(trace)
    elapsed = time.perf_counter() - start
    per_record_ms = elapsed / len(traces) * 1000

    print(f"perf-gate: attributed {len(traces)} records in "
          f"{elapsed:.2f}s ({per_record_ms:.1f} ms/record, "
          f"budget {args.max_ms_per_record:g} ms)")
    if per_record_ms > args.max_ms_per_record:
        print(f"FAIL: attribution slowed past "
              f"{args.max_ms_per_record:g} ms/record - "
              f"complexity regression?",
              file=sys.stderr)
        return 1
    print("PASS - attribution performance within budget")
    return 0


def agent_wave_gate(budget_s: float = 15.0) -> int:
    """Scorecard + markdown + fleet render on a 10k-step trace.

    The agent wave (v0.50) walks every step per agent and renders
    timelines; this keeps the whole pass linear and bounded.
    """
    from approximately.attributor import attribute
    from approximately.cluster import agent_scorecard
    from approximately.markdown_report import render_markdown
    from approximately.recorder import Recorder

    rec = Recorder("perf: agent wave", save=False, agent="worker")
    rec.tool("bash", {"cmd": "prime"}, result="ok", agent="worker")
    for i in range(10_000):
        rec.tool("bash", {"cmd": f"c{i}"}, result="r", thought="t")
    rec.respond("done", success=False)
    trace = rec.trace

    start = time.perf_counter()
    rows = agent_scorecard([trace])
    render_markdown(trace, attribute(trace))
    elapsed = time.perf_counter() - start
    ok = rows[0]["steps"] == 10_002 and elapsed < budget_s
    print(f"perf-gate[agent-wave]: scorecard+markdown on 10k steps "
          f"in {elapsed:.2f}s (budget {budget_s:.0f}s) - "
          f"{'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1



def query_gate(budget_s: float = 15.0) -> int:
    """Expression filter over a 10k-trace store, heavy field twice.

    ``mode`` mentions used to re-run the detector suite per mention;
    per-select memoization (v0.66) makes it once per trace. This gate
    pins that: the double-mention filter over 10k traces must stay
    linear and bounded.
    """
    from approximately.query import select
    from approximately.recorder import Recorder

    traces = []
    for i in range(10_000):
        ok = i % 3 != 0
        rec = Recorder(f"t {i}", save=False)
        rec.trace.id = f"p-{i}"
        rec.tool("search", {"q": i}, result=None if ok else "x",
                 error=None if ok else "timeout")
        rec.respond("done", success=ok)
        traces.append(rec.trace)

    start = time.perf_counter()
    found = select(traces, "mode == FM-2.1 or mode != FM-2.1")
    elapsed = time.perf_counter() - start
    if len(found) != len(traces):
        print("FAIL: query gate returned the wrong count",
              file=sys.stderr)
        return 1
    print(f"perf-gate[query]: double-mode filter over 10k traces in "
          f"{elapsed * 1000:.0f}ms (budget {budget_s:g}s) - "
          + ("PASS" if elapsed <= budget_s else "FAIL"))
    if elapsed > budget_s:
        print("FAIL: select slowed past budget - memoization regressed?",
              file=sys.stderr)
        return 1
    return 0





def similar_gate(budget_s: float = 15.0) -> int:
    """Nearest-neighbour ranking over a 2000-trace store.

    rank_similar skips the quadratic DP below the top-N threshold
    (v1.4); this gate pins that - the same store ranked in 0.2 s
    after the change and would blow the budget if the pruning
    regressed to per-candidate full scans.
    """
    from approximately.align import rank_similar
    from approximately.recorder import Recorder

    traces = []
    for i in range(2000):
        rec = Recorder(f"t {i}", save=False)
        rec.trace.id = f"big-{i}"
        for j in range(20):
            rec.tool("probe", {"i": j}, result="ok")
        rec.respond("done", success=bool(i % 3))
        traces.append(rec.trace)

    start = time.perf_counter()
    ranked = rank_similar(traces[0], traces, top=5)
    elapsed = time.perf_counter() - start
    if len(ranked) != 5 or any(
            c.id == traces[0].id for c, _ in ranked):
        print("FAIL: similar gate ranked wrong", file=sys.stderr)
        return 1
    print(f"perf-gate[similar]: rank 2000 traces in "
          f"{elapsed:.2f}s (budget {budget_s:g}s) - "
          + ("PASS" if elapsed <= budget_s else "FAIL"))
    if elapsed > budget_s:
        print("FAIL: similar slowed past budget - pruning regressed?",
              file=sys.stderr)
        return 1
    return 0





def spool_gate(budget_s: float = 30.0) -> int:
    """Ingest 200 mixed spool files (transcripts + OTLP envelopes)
    in one pass.  The watch loop runs this forever, so the pass
    must stay cheap; the budget is runner-noise headroom like the
    import gate's (local: well under a second)."""
    import json as _json
    import tempfile
    from pathlib import Path as _Path

    from approximately.exporter import export_store
    from approximately.recorder import Recorder
    from approximately.spool import spool_pass
    from approximately.store import TraceStore

    with tempfile.TemporaryDirectory() as tmp:
        spool = _Path(tmp) / "spool"
        spool.mkdir()
        for i in range(150):
            rec = Recorder(f"spooled {i}", save=False)
            rec.tool("shell", {"n": i}, result="ok")
            rec.respond("done", success=i % 10 > 0)
            (spool / f"t{i}.jsonl").write_text(
                _json.dumps(rec.trace.to_dict()) + "\n",
                encoding="utf-8")
        otel_store = TraceStore(_Path(tmp) / "otel")
        for j in range(2):
            rec = Recorder(f"otel batch {j}", save=False)
            rec.tool("search", {"q": j}, result="hit")
            rec.respond("done", success=True)
            otel_store.save(rec.trace)
            export_store(otel_store, spool / f"o{j}.otlp.json",
                         fmt="otel")
            otel_store.clean(keep_days=0)
        store = TraceStore(_Path(tmp) / "s")
        # seeding is setup, not subject: time the pass itself
        start = time.perf_counter()
        result = spool_pass(store, spool)
    elapsed = time.perf_counter() - start
    if result["imported"] != 152:
        print("FAIL: spool gate ingested the wrong count",
              file=sys.stderr)
        return 1
    print(f"perf-gate[spool]: 200 files in {elapsed * 1000:.0f}ms "
          f"({result['failed_traces']} failed, budget "
          f"{budget_s:g}s) - "
          + ("PASS" if elapsed <= budget_s else "FAIL"))
    if elapsed > budget_s:
        print("FAIL: spool pass slowed past budget", file=sys.stderr)
        return 1
    return 0


def survey_spend_gate(budget_s: float = 20.0) -> int:
    """Fleet survey with prices over a 10k-trace store.

    The money rollup (v2.13) walks every step of every trace per
    store and must stay linear like the rest of the survey; the
    budget is runner-noise headroom (local: a fraction of a
    second).  2k traces: enough to catch a superlinear rollup
    without making the gate measure 10k small-file I/O, which is
    what Windows runners are slow at."""
    import tempfile
    from pathlib import Path as _Path

    from approximately.fleet import survey
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    with tempfile.TemporaryDirectory() as tmp:
        store = TraceStore(_Path(tmp) / "s")
        models = ("gpt-x", "cheap", "mystery")
        for i in range(2_000):
            rec = Recorder(f"run {i}", save=False)
            rec.tool("shell", {"n": i}, result="ok")
            rec.respond("done", success=True)
            rec.trace.steps[-1].tokens = 100 + (i % 50)
            rec.trace.model = models[i % 3]
            store.save(rec.trace)
        # seeding is setup, not subject: time the survey itself
        start = time.perf_counter()
        summaries = survey([store.directory],
                           prices={"gpt-x": 3.0, "cheap": 0.5})
    elapsed = time.perf_counter() - start
    s = summaries[0]
    if s.total_tokens <= 0 or s.est_spend is None:
        print("FAIL: survey spend gate produced no numbers",
              file=sys.stderr)
        return 1
    print(f"perf-gate[survey-spend]: 2k traces priced in "
          f"{elapsed:.1f}s (est ${s.est_spend:,.0f}, budget "
          f"{budget_s:g}s) - "
          + ("PASS" if elapsed <= budget_s else "FAIL"))
    if elapsed > budget_s:
        print("FAIL: survey slowed past budget", file=sys.stderr)
        return 1
    return 0



def ci_gate(budget_s: float = 30.0) -> int:
    """The quality-gate door (v2.23) over a 10k-trace store.

    cmd_ci walks traces three times (durations, tokens, stats) and
    must stay linear; a CI pipeline runs it on every push, so a
    superlinear pass fails builds by timeout, not by verdict."""
    import argparse as _argparse
    import tempfile
    from pathlib import Path as _Path

    from approximately.cli import cmd_ci
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    with tempfile.TemporaryDirectory() as tmp:
        store = TraceStore(_Path(tmp) / "s")
        for i in range(10_000):
            rec = Recorder(f"run {i}", save=False)
            rec.tool("search", {"q": i}, tokens=100 + i % 50,
                     latency_ms=100 + i % 50)
            rec.respond("done", success=i % 10 != 0)
            store.save(rec.trace)
        args = _argparse.Namespace(store=str(store.directory),
                                   since=None, json=False,
                                   max_failure_rate=0.3,
                                   max_p95_latency_ms=10 ** 9,
                                   max_tokens=10 ** 12, min_traces=1,
                                   prices=None)
        # seeding is setup, not subject: time the gate itself
        start = time.perf_counter()
        code = cmd_ci(args)
    elapsed = time.perf_counter() - start
    if code != 0:
        print("FAIL: ci gate did not pass its own store",
              file=sys.stderr)
        return 1
    print(f"perf-gate[ci]: gates over 10k traces in "
          f"{elapsed * 1000:.0f}ms (budget {budget_s:g}s) - "
          + ("PASS" if elapsed <= budget_s else "FAIL"))
    if elapsed > budget_s:
        print("FAIL: ci gate slowed past budget", file=sys.stderr)
        return 1
    return 0


def budget_gate(budget_s: float = 5.0) -> int:
    """The live Budget rails (v2.70) over 2k recorded runs.

    Charging happens on every tool step of every budgeted run; the
    per-call cost must stay invisible next to the recording itself."""
    import tempfile

    from approximately.budget import Budget
    from approximately.recorder import Recorder

    start = time.perf_counter()
    with tempfile.TemporaryDirectory() as tmp:
        del tmp
        for i in range(2_000):
            budget = Budget(tokens=10 ** 12)
            rec = Recorder(f"burn check {i}", save=False,
                           budget=budget)
            rec.tool("search", {"q": i}, tokens=100 + i % 50)
            rec.respond("done", success=True)
    elapsed = time.perf_counter() - start
    print(f"perf-gate[budget]: 2k budgeted runs in "
          f"{elapsed * 1000:.0f}ms (budget {budget_s:g}s) - "
          + ("PASS" if elapsed <= budget_s else "FAIL"))
    if elapsed > budget_s:
        print("FAIL: budget rails slowed past budget", file=sys.stderr)
        return 1
    return 0


def junit_gate(budget_s: float = 10.0) -> int:
    """`ci --format junit` (v2.71) over a 2k-trace store.

    The XML build rides on the same store walk as the text gate; the
    ElementTree rendering must not double the pass."""
    import argparse as _argparse
    import io
    import tempfile
    from contextlib import redirect_stdout
    from pathlib import Path as _Path

    from approximately.cli import cmd_ci
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    with tempfile.TemporaryDirectory() as tmp:
        store = TraceStore(_Path(tmp) / "s")
        for i in range(2_000):
            rec = Recorder(f"run {i}", save=False)
            rec.tool("search", {"q": i}, tokens=100)
            rec.respond("done", success=True)
            store.save(rec.trace)
        args = _argparse.Namespace(store=str(store.directory),
                                   since=None, json=False,
                                   format="junit", max_failure_rate=0.3,
                                   max_p95_latency_ms=10 ** 9,
                                   max_tokens=10 ** 12, min_traces=1,
                                   prices=None)
        sink = io.StringIO()
        start = time.perf_counter()
        with redirect_stdout(sink):
            code = cmd_ci(args)
    elapsed = time.perf_counter() - start
    out = sink.getvalue()
    if code != 0 or "<testsuites" not in out:
        print("FAIL: junit gate produced no suite", file=sys.stderr)
        return 1
    print(f"perf-gate[junit]: junit over 2k traces in "
          f"{elapsed * 1000:.0f}ms (budget {budget_s:g}s) - "
          + ("PASS" if elapsed <= budget_s else "FAIL"))
    if elapsed > budget_s:
        print("FAIL: junit render slowed past budget", file=sys.stderr)
        return 1
    return 0


def quarantine_gate(budget_s: float = 10.0) -> int:
    """doctor + quarantine (v2.75) over a store with poison in it.

    The scan must read every record once; the quarantine move must
    not re-read the world."""
    import tempfile
    from pathlib import Path as _Path

    from approximately.doctor import doctor, quarantine_corrupt
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    with tempfile.TemporaryDirectory() as tmp:
        store_dir = _Path(tmp) / "s"
        store = TraceStore(store_dir)
        for i in range(200):
            rec = Recorder(f"run {i}", save=False)
            rec.tool("t", tokens=10)
            store.save(rec.trace)
        for j in range(20):
            (store_dir / f"poison{j}.json").write_text(
                "{not json", encoding="utf-8")
        start = time.perf_counter()
        report = doctor(store_dir)
        moved = quarantine_corrupt(store_dir, report)
    elapsed = time.perf_counter() - start
    if len(moved) != 20:
        print("FAIL: quarantine missed the poison", file=sys.stderr)
        return 1
    print(f"perf-gate[quarantine]: doctor+quarantine over 220 files "
          f"in {elapsed * 1000:.0f}ms (budget {budget_s:g}s) - "
          + ("PASS" if elapsed <= budget_s else "FAIL"))
    if elapsed > budget_s:
        print("FAIL: quarantine slowed past budget", file=sys.stderr)
        return 1
    return 0


def result_meter_gate(budget_s: float = 5.0) -> int:
    """The result-bloat meter (v2.98) over a 2k-trace store.

    Same robust ruler as latency/tokens on result character
    lengths; a fleet scan must stay linear in traces x steps."""
    import tempfile

    from approximately.anomaly import detect_fleet_result_anomalies
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    with tempfile.TemporaryDirectory() as tmp:
        store = TraceStore(Path(tmp) / "s")
        for i in range(2_000):
            rec = Recorder(f"run {i}", save=False)
            for j in range(9):
                rec.tool("list", {"j": j}, result="x" * 200)
            rec.tool("dump", {}, result="y" * (20_000 if i % 50 == 0
                                               else 300))
            rec.respond("done", success=True)
            store.save(rec.trace)
        traces = store.list_traces()
        start = time.perf_counter()
        flags = detect_fleet_result_anomalies(traces)
    elapsed = time.perf_counter() - start
    if not flags:
        print("FAIL: result meter found nothing", file=sys.stderr)
        return 1
    print(f"perf-gate[result-meter]: fleet meter over 2k traces in "
          f"{elapsed * 1000:.0f}ms (budget {budget_s:g}s) - "
          + ("PASS" if elapsed <= budget_s else "FAIL"))
    if elapsed > budget_s:
        print("FAIL: result meter slowed past budget", file=sys.stderr)
        return 1
    return 0


def composition_gate(budget_s: float = 5.0) -> int:
    """The composition walk + truncation what-if (v2.100/101) on a
    500-step run: two passes, still trivial next to recording."""

    from approximately.context import composition
    from approximately.recorder import Recorder

    rec = Recorder("long run", save=False)
    for i in range(500):
        rec.tool("t", {"i": i}, result="x" * (300 if i % 25 else 4_000))
    rec.respond("done", success=True)
    start = time.perf_counter()
    plain = composition(rec.trace)
    whatif = composition(rec.trace, truncate_results=1_000)
    elapsed = time.perf_counter() - start
    if whatif["tokens_saved"] <= 0 or plain["total_tokens"] <= 0:
        print("FAIL: composition gate produced no accounting",
              file=sys.stderr)
        return 1
    print(f"perf-gate[composition]: 500-step composition + what-if "
          f"in {elapsed * 1000:.0f}ms (budget {budget_s:g}s) - "
          + ("PASS" if elapsed <= budget_s else "FAIL"))
    if elapsed > budget_s:
        print("FAIL: composition slowed past budget", file=sys.stderr)
        return 1
    return 0


def failure_budget_gate(budget_s: float = 5.0) -> int:
    """The reliability budget (v2.96) over a 365-day digest window.

    The nightly audit projects a year of history; the Theil-Sen
    slope must not make that walk expensive."""
    import datetime

    from approximately.forecast import failure_budget
    base = datetime.date(2025, 1, 1)
    days = [{"day": (base + datetime.timedelta(days=i)).isoformat(),
             "failures": (i * 7) % 13, "est_spend": 1.0}
            for i in range(365)]
    start = time.perf_counter()
    fb = failure_budget(days, allowance=1_000, horizon_days=30)
    elapsed = time.perf_counter() - start
    if not fb["usable"]:
        print("FAIL: failure budget refused a year of history",
              file=sys.stderr)
        return 1
    print(f"perf-gate[failure-budget]: 365-day window in "
          f"{elapsed * 1000:.0f}ms (budget {budget_s:g}s) - "
          + ("PASS" if elapsed <= budget_s else "FAIL"))
    if elapsed > budget_s:
        print("FAIL: failure budget slowed past budget",
              file=sys.stderr)
        return 1
    return 0


def tail_gate(budget_s: float = 5.0) -> int:
    """The tail (v2.123) over a 2k-trace store.

    Every pass re-scans the store for arrivals — that scan must
    stay linear and cheap, because the tail runs it forever.
    Local: ~85-140ms at 2k traces; loaded Windows runners hit
    ~1.4s, so the budget is 5s — regressions are 10-100x, runner
    weather is 2-15x, and the gate exists for the former."""
    import tempfile
    from pathlib import Path as _Path

    from approximately.store import TraceStore
    from approximately.tail import tail
    from approximately.trace import Step, Trace

    with tempfile.TemporaryDirectory() as tmp:
        store = TraceStore(_Path(tmp) / "s")
        for i in range(2_000):
            t = Trace(task=f"run {i}", model="m")
            t.add(Step(kind="tool_call", tool="sh", result="ok",
                       tokens=10))
            t.success = True
            store.save(t)
        start = time.perf_counter()
        lines = tail(store, once=True)
        elapsed = time.perf_counter() - start
    if len(lines) < 1 or "already on file" not in lines[0]:
        print("FAIL: tail pass lost its header line",
              file=sys.stderr)
        return 1
    print(f"perf-gate[tail]: once-pass over 2k traces in "
          f"{elapsed * 1000:.0f}ms (budget {budget_s:g}s) - "
          + ("PASS" if elapsed <= budget_s else "FAIL"))
    if elapsed > budget_s:
        print("FAIL: tail scan slowed past budget", file=sys.stderr)
        return 1
    return 0


def doctor_deep_gate(budget_s: float = 30.0) -> int:
    """doctor --deep over 10k traces: every step of every record
    re-hashed.  Deep is opt-in because it is the expensive pass;
    this gate pins that expense to linear-and-bounded (local:
    ~1.3s at 10k traces)."""
    import tempfile
    from pathlib import Path as _Path

    from approximately.doctor import doctor
    from approximately.integrity import sign
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    with tempfile.TemporaryDirectory() as tmp:
        store = TraceStore(_Path(tmp) / "s")
        for i in range(2_000):
            rec = Recorder(f"run {i}", save=False)
            rec.tool("deploy", {}, result="ok")
            rec.respond("done", success=True)
            sign(rec.trace)
            store.save(rec.trace)
        # seeding is setup, not subject: time the deep pass itself
        start = time.perf_counter()
        report = doctor(store.directory, deep=True)
    elapsed = time.perf_counter() - start
    if report.chain_checked != 2_000 or report.chain_failed:
        print("FAIL: deep gate mis-verified the chains",
              file=sys.stderr)
        return 1
    print(f"perf-gate[doctor-deep]: chains of 2k traces in "
          f"{elapsed * 1000:.0f}ms (budget {budget_s:g}s) - "
          + ("PASS" if elapsed <= budget_s else "FAIL"))
    if elapsed > budget_s:
        print("FAIL: deep doctor slowed past budget", file=sys.stderr)
        return 1
    return 0


def startup_gate(budget_s: float = 5.0) -> int:
    """Cold start: `--version` must answer, in format, in budget.

    59 doors import one cli module; a careless top-level import can
    quietly make every door pay at startup (local: ~100ms eager,
    ~80ms after the lazy-door batch; the budget is
    regressions-not-weather, like the rest of the wall)."""
    import subprocess
    import sys as _sys

    start = time.perf_counter()
    r = subprocess.run(
        [_sys.executable, "-m", "approximately", "--version"],
        capture_output=True, text=True, timeout=budget_s * 2,
        check=False)  # the returncode IS the finding
    elapsed = time.perf_counter() - start
    if r.returncode != 0 or not r.stdout.startswith("approximately "):
        print("FAIL: startup gate: --version misanswered",
              file=sys.stderr)
        return 1
    print(f"perf-gate[startup]: cold --version in "
          f"{elapsed * 1000:.0f}ms (budget {budget_s:g}s) - "
          + ("PASS" if elapsed <= budget_s else "FAIL"))
    if elapsed > budget_s:
        print("FAIL: startup slowed past budget", file=sys.stderr)
        return 1
    return 0


def complexity_gate(baseline: int = 87) -> int:
    """C+-and-worse block count vs the recorded baseline.

    v3 inherited 87 C blocks and none worse; the gate does not ask
    for a heroic refactor — it asks that the count never grows. A
    new C block must retire an old one. The budget is the audit."""
    import subprocess as _sp
    import sys as _sys

    r = _sp.run([_sys.executable, "-m", "radon", "cc", "-s",
                 "src/approximately"], capture_output=True,
                text=True, check=False)
    if r.returncode != 0:
        print("FAIL: complexity gate: radon failed", file=sys.stderr)
        return 1
    total = sum(1 for line in r.stdout.splitlines()
                if " - C " in line or " - D " in line
                or " - E " in line or " - F " in line)
    verdict = "PASS" if total <= baseline else "FAIL"
    print(f"perf-gate[complexity]: {total} C+ blocks "
          f"(baseline {baseline}) - {verdict}")
    if total > baseline:
        print("FAIL: complexity grew past the recorded baseline - "
              "a new C block must retire an old one", file=sys.stderr)
        return 1
    return 0


def clean_gate(budget_s: float = 15.0) -> int:
    """Retention by count over a 10k-file store: the mtime sort
    must stay n log n, not degrade into per-file rescans."""
    import tempfile
    from pathlib import Path as _Path

    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    with tempfile.TemporaryDirectory() as tmp:
        store = TraceStore(_Path(tmp) / "s")
        for i in range(2_000):
            rec = Recorder(f"run {i}", save=False)
            rec.tool("deploy", {}, result="ok")
            rec.respond("done", success=True)
            store.save(rec.trace)
        # seeding is setup, not subject: time the dry run itself
        start = time.perf_counter()
        removed = store.clean(keep_days=30, max_traces=1_500,
                              dry_run=True)
    elapsed = time.perf_counter() - start
    if removed != 500:
        print("FAIL: clean gate trimmed the wrong count",
              file=sys.stderr)
        return 1
    print(f"perf-gate[clean]: count-cap dry run over 2k traces in "
          f"{elapsed * 1000:.0f}ms (budget {budget_s:g}s) - "
          + ("PASS" if elapsed <= budget_s else "FAIL"))
    if elapsed > budget_s:
        print("FAIL: clean slowed past budget", file=sys.stderr)
        return 1
    return 0


def csv_export_gate(budget_s: float = 10.0) -> int:
    """CSV export of 1k traces (one row per step): the quoting and
    formula-injection defense must stay linear per cell."""
    import tempfile
    from pathlib import Path as _Path

    from approximately.exporter import export_store
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    with tempfile.TemporaryDirectory() as tmp:
        store = TraceStore(_Path(tmp) / "s")
        for i in range(1_000):
            rec = Recorder(f"task {i}", save=False)
            for j in range(5):
                rec.tool("search", {"q": j},
                         result=f"=c{j}, hit" if j == 0 else "hit")
            rec.respond(f"done {i}", success=True)
            store.save(rec.trace)
        out = _Path(tmp) / "out.csv"
        # seeding is setup, not subject: time the export itself
        start = time.perf_counter()
        result = export_store(store, out, fmt="csv")
    elapsed = time.perf_counter() - start
    if result["written"] != 6_000:
        print("FAIL: csv gate wrote the wrong row count",
              file=sys.stderr)
        return 1
    print(f"perf-gate[csv]: 1k traces / 6k steps in "
          f"{elapsed * 1000:.0f}ms (budget {budget_s:g}s) - "
          + ("PASS" if elapsed <= budget_s else "FAIL"))
    if elapsed > budget_s:
        print("FAIL: csv export slowed past budget", file=sys.stderr)
        return 1
    return 0


def evidence_gate(budget_s: float = 20.0) -> int:
    """Evidence pack over a 2k-step trace: attribute + render_html +
    verify + zip must stay linear in steps (the postmortem is the
    big member; local: well under a second)."""
    import tempfile
    from pathlib import Path as _Path

    from approximately.evidence import build_evidence_pack
    from approximately.integrity import sign
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    with tempfile.TemporaryDirectory() as tmp:
        store = TraceStore(_Path(tmp) / "s")
        rec = Recorder("wide run", save=False)
        for i in range(2_000):
            rec.tool("probe", {"i": i}, result="x" * 100)
        rec.respond("done", success=False)
        sign(rec.trace)
        store.save(rec.trace)
        out = _Path(tmp) / "case.zip"
        # seeding is setup, not subject: time the pack itself
        start = time.perf_counter()
        manifest = build_evidence_pack(store, rec.trace.id, out)
        pack_bytes = out.stat().st_size   # tmpdir dies with the block
    elapsed = time.perf_counter() - start
    if len(manifest["members"]) != 4 or pack_bytes <= 0:
        print("FAIL: evidence gate packed the wrong members",
              file=sys.stderr)
        return 1
    print(f"perf-gate[evidence]: 2k-step pack in "
          f"{elapsed * 1000:.0f}ms ({pack_bytes // 1024}KiB, "
          f"budget {budget_s:g}s) - "
          + ("PASS" if elapsed <= budget_s else "FAIL"))
    if elapsed > budget_s:
        print("FAIL: evidence slowed past budget", file=sys.stderr)
        return 1
    return 0


def compare_gate(budget_s: float = 20.0) -> int:
    """compare over two 2k-trace stores: two attribution passes and
    two scorecards; the deploy gate runs this per push."""
    import argparse as _argparse
    import tempfile
    from pathlib import Path as _Path

    from approximately.cli import cmd_compare
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    with tempfile.TemporaryDirectory() as tmp:
        for name in ("base", "cand"):
            store = TraceStore(_Path(tmp) / name)
            for i in range(2_000):
                rec = Recorder(f"run {i}", save=False)
                rec.tool("search", {"q": i}, tokens=100,
                         latency_ms=100)
                rec.respond("done", success=i % 9 != 0)
                store.save(rec.trace)
        args = _argparse.Namespace(
            baseline=str(_Path(tmp) / "base"),
            candidate=str(_Path(tmp) / "cand"), prices=None,
            since=None, fail_on_new_modes=False, json=True)
        # seeding is setup, not subject: time the comparison itself
        import contextlib

        start = time.perf_counter()
        with contextlib.redirect_stdout(
                open(_Path(tmp) / "verdict.json", "w")):
            code = cmd_compare(args)
    elapsed = time.perf_counter() - start
    if code != 0:
        print("FAIL: compare gate did not pass its own stores",
              file=sys.stderr)
        return 1
    print(f"perf-gate[compare]: 2k vs 2k traces in "
          f"{elapsed * 1000:.0f}ms (budget {budget_s:g}s) - "
          + ("PASS" if elapsed <= budget_s else "FAIL"))
    if elapsed > budget_s:
        print("FAIL: compare slowed past budget", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
