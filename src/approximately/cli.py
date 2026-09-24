"""approximately command line interface."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__
from .attributor import attribute
from .demo import run_demo
from .regress import render_regression
from .replayer import replay
from .report import render_html
from .store import TraceStore
from .taxonomy import CATEGORY_NAMES, all_modes
from .trace import Trace


def _load_trace(spec: str, store: TraceStore) -> Trace:
    if spec == "latest":
        files = sorted(store.directory.glob("*.json"),
                       key=lambda p: p.stat().st_mtime)
        if not files:
            raise SystemExit(f"error: the store {store.directory} is empty")
        spec = files[-1].stem
    trace = store.load(spec)
    if trace is None:
        raise SystemExit(f"error: no trace found for {spec!r} "
                         f"(looked in {store.directory})")
    return trace


def _resolve_executor(expr: str):
    module_name, _, attr = expr.partition(":")
    if not attr:
        raise SystemExit("error: executor must look like 'package.module:func'")
    module = importlib.import_module(module_name)
    return getattr(module, attr)


def _print_report(report, judge_note: str = "",
                  top: int = 0) -> None:
    bar = "─" * 62
    print(bar)
    print(f"  VERDICT  {report.primary_mode.label}")
    if judge_note:
        print(f"  {judge_note}")
    print(f"  {report.summary}")
    print(bar)
    if top and report.runner_ups:
        print("  RUNNER-UP HYPOTHESES (detectors also fired for)")
        for r in report.runner_ups[:top]:
            print(f"    {r['mode']} {r['label']} - "
                  f"{r['detections']} detection(s), max confidence "
                  f"{r['max_confidence']:.2f}")
    for det in report.detections:
        print(f"  · {det.mode_id} via {det.source} "
              f"(confidence {det.confidence:.2f}) — step #{det.step_index}")
        for ev in det.evidence:
            print(f"      - {ev}")
    if report.disagreement:
        print(f"  ⚠ {report.disagreement}")
    if report.suggested_fixes:
        print("  SUGGESTED FIXES")
        for i, fix in enumerate(report.suggested_fixes, 1):
            print(f"    {i}. {fix}")
    print(bar)


def cmd_demo(args: argparse.Namespace) -> int:
    if args.scenario == "multi-agent":
        from .demo_multiagent import run_demo as run_multiagent
        trace, report, path = run_multiagent()
    elif args.scenario == "verification":
        from .demo_verification import run_demo as run_verification
        from .store import TraceStore

        store_dir = (TraceStore(args.store).directory
                     if getattr(args, "store", None) else None)
        trace, report, path = run_verification(store_dir)
    elif args.scenario == "loop":
        from .demo_loop import run_demo as run_loop
        from .store import TraceStore

        store_dir = (TraceStore(args.store).directory
                     if getattr(args, "store", None) else None)
        trace, report, path = run_loop(store_dir)
    else:
        # honor --store (before it was accepted and silently ignored)
        from .store import TraceStore

        store_dir = (TraceStore(args.store).directory
                     if getattr(args, "store", None) else None)
        trace, report, path = run_demo(store_dir)
    print(f"recorded demo trace {trace.id} ({len(trace.steps)} steps)")
    _print_report(report)

    from .context import default_facts, forecast

    fc = forecast(trace, budget=args.context_budget, facts=default_facts(trace))
    print()
    bar = "─" * 62
    print(bar)
    print(f"  CONTEXT RUNTIME — what a {args.context_budget}-token budget "
          f"would do to this run")
    print(bar)
    for line in fc.summary().splitlines():
        print(f"  {line}")
    print(bar)

    print(f"HTML report: {path}")
    if args.open and path is not None:
        import webbrowser

        webbrowser.open(path.as_uri())
    print("\nNext: point Recorder at your own agent — "
          "https://github.com/B1ueMu3ic4m/approximately#quickstart")
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    from .replayer import compare

    store = TraceStore(args.store)
    trace = _load_trace(args.trace, store)
    executor = _resolve_executor(args.executor)
    diff = replay(trace, executor, threshold=args.threshold)
    diff_b = None
    if args.patched:
        patched = _resolve_executor(args.patched)
        diff_b = replay(trace, patched, threshold=args.threshold)
        print(compare(diff, diff_b))
        print("--- original:")
        print(diff.summary())
        print("--- patched:")
        print(diff_b.summary())
    else:
        print(diff.summary())
    if getattr(args, "html", None):
        from .replayer import render_replay_html

        out = Path(args.html)
        out.write_text(render_replay_html(diff, diff_b), encoding="utf-8")
        print(f"wrote replay page: {out}")
    if diff.verdict == "diverged" and not args.patched:
        return 1
    return 0


def cmd_test(args: argparse.Namespace) -> int:
    store = TraceStore(args.store)
    trace = _load_trace(args.trace, store)
    report = attribute(trace)
    budget = args.budget if args.budget else None
    out = Path(args.output) if args.output else Path(f"test_approximately_{trace.id}.py")
    out.write_text(render_regression(trace, report, budget=budget,
                                     min_recall=args.min_recall), encoding="utf-8")
    print(f"wrote {out}")
    print("wire EXECUTOR (replay guard) and AGENT_ENTRY (contract guards), "
          "then run: pytest " + str(out))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from .cluster import trend
    from .report import render_index_html

    store = TraceStore(args.store)
    if args.all:
        pairs = []
        traces = []
        written = 0
        for trace in store.list_traces():
            report = attribute(trace, use_judge=args.judge)
            pairs.append((trace, report))
            traces.append(trace)
            # write every individual report so the index links resolve
            page = store.directory / f"{trace.id}.report.html"
            if not page.exists():
                page.write_text(render_html(trace, report), encoding="utf-8")
                written += 1
        out = Path(args.output) if args.output else store.directory / "index.html"
        out.write_text(render_index_html(pairs, trend_rows=trend(traces)),
                       encoding="utf-8")
        print(f"wrote index over {len(pairs)} traces: {out} "
              f"({written} individual reports generated)")
        return 0
    trace = _load_trace(args.trace, store)
    report = attribute(trace, use_judge=args.judge)
    if getattr(args, "markdown", False):
        from .markdown_report import render_markdown

        md = Path(args.output) if args.output else \
            store.directory / f"{trace.id}.report.md"
        md.write_text(render_markdown(trace, report), encoding="utf-8")
        print(f"wrote markdown postmortem: {md}")
        return 0
    out = Path(args.output) if args.output else store.directory / f"{trace.id}.report.html"
    out.write_text(render_html(trace, report), encoding="utf-8")
    print(f"wrote {out}")
    if getattr(args, "mermaid", None):
        from .mermaid import render_mermaid

        mmd = Path(args.mermaid)
        mmd.write_text(render_mermaid(trace, report.detections),
                       encoding="utf-8")
        print(f"wrote mermaid sequence diagram: {mmd}")
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    from .context import default_facts, forecast

    store = TraceStore(args.store)
    trace = _load_trace(args.trace, store)
    facts = default_facts(trace) if not args.facts else json.loads(
        Path(args.facts).read_text(encoding="utf-8")
    )
    fc = forecast(trace, budget=args.budget, facts=facts)
    print(fc.summary())
    return 0


def cmd_taxonomy(_args: argparse.Namespace) -> int:
    print("MAST failure taxonomy (Cemri et al., arXiv:2503.13657)\n")
    current_category = None
    for mode in all_modes():
        if mode.category != current_category and mode.id != "OTHER":
            current_category = mode.category
            share = {"FC1": 41.77, "FC2": 36.94, "FC3": 21.30}[mode.category]
            print(f"[{mode.category}] {CATEGORY_NAMES[mode.category]} "
                  f"({share}% of failures)")
        share_text = (f" {mode.mast_share:5.2f}% of traces"
                      if mode.mast_share else "")
        print(f"  {mode.id:<7} {mode.name}{share_text}")
    return 0


def cmd_explain(args: argparse.Namespace) -> int:
    from .explain import explain_overview, explain_text
    from .taxonomy import FAILURE_MODES

    if not args.mode:
        print(explain_overview())
        return 0
    if args.mode not in FAILURE_MODES:
        valid = ", ".join(sorted(FAILURE_MODES))
        print(f"unknown failure mode {args.mode!r}; valid ids: {valid}",
              file=sys.stderr)
        return 1
    print(explain_text(args.mode))
    return 0


def cmd_bench_gate(args: argparse.Namespace) -> int:
    from .benchgate import run_gate

    return run_gate(Path(args.dataset), Path(args.floors), args.label)


def cmd_optimize(args: argparse.Namespace) -> int:
    from .context import optimize_budget

    store = TraceStore(args.store)
    trace = _load_trace(args.trace, store)
    result = optimize_budget(trace, min_recall=args.min_recall)
    if result is None:
        print("no probe facts in this trace — nothing to optimize")
        return 1
    print(result.summary())
    print(f"  set Recorder budget to {result.minimal_budget} to lock it in")
    return 0


def cmd_similar(args: argparse.Namespace) -> int:
    from .align import rank_similar

    store = TraceStore(args.store)
    trace = _load_trace(args.trace, store)
    ranked = rank_similar(trace, store.list_traces(), top=args.top)
    if not ranked:
        print("no other traces in the store to compare against")
        return 0
    print(f"most alignment-similar traces to {trace.id}:")
    for candidate, score in ranked:
        print(f"  {score:.2f}  {candidate.id}  {candidate.task[:56]}")
    return 0


def cmd_predict(args: argparse.Namespace) -> int:
    from .precursor import PrecursorModel

    store = TraceStore(args.store)
    trace = _load_trace(args.trace, store)
    model = PrecursorModel()
    for t in store.list_traces():
        if t.id != trace.id:
            model.observe(t)
    score = model.probability(trace)
    print(score.summary())
    return 0


def cmd_calibrate(args: argparse.Namespace) -> int:
    from .attributor import score_modes
    from .calibration import (
        ConformalModel,
        expected_calibration_error,
        fit_conformal,
        fit_temperature,
    )
    from .distill import load_dataset

    labeled = load_dataset(Path(args.dataset), fmt=args.format)
    if len(labeled) < 10:
        print(f"need >= 10 labeled traces, got {len(labeled)}")
        return 1
    if any(isinstance(gold, list) for _, gold in labeled):
        print("calibrate scores one gold per trace; this dataset is "
              "multi-label - use `benchmark --multi-label` for it")
        return 1
    scored = [(score_modes(t), gold) for t, gold in labeled]
    split = max(1, int(len(scored) * 0.5))
    temperature = fit_temperature(scored[:split])
    model = fit_conformal(scored[:split], alpha=args.alpha,
                          temperature=temperature)
    model.scores_of = score_modes

    held = scored[split:]
    covered, ece_pairs = 0, []
    for scores, gold in held:
        modes, probs = model.prediction_set(scores)
        covered += gold in modes
        ece_pairs.append((probs.get(gold, 0.0), True))
        ece_pairs.append((1 - probs.get(gold, 0.0), False))
    ece = expected_calibration_error(ece_pairs)
    print(f"calibration split {split} · held-out {len(held)} · "
          f"temperature {temperature}")
    print(f"coverage: {covered}/{len(held)} "
          f"(target >= {model.target_coverage:.0%} at alpha={args.alpha})")
    print(f"ECE on held-out (gold-probability view): {ece:.3f}")
    if isinstance(model, ConformalModel) and model.threshold:
        print(f"conformal threshold (nonconformity): {model.threshold:.3f}")
    return 0


def cmd_rotate(args: argparse.Namespace) -> int:
    from .integrity import load_key, rotate

    store = TraceStore(args.store)
    trace = _load_trace(args.trace, store)
    old_key = load_key(args.old_key_file)
    new_key = load_key(args.new_key_file)
    if new_key is None:
        raise SystemExit("error: --new-key-file is required "
                         "(or set APPROXIMATELY_SIGNING_KEY)")
    try:
        rotate(trace, old_key=old_key, new_key=new_key)
    except ValueError as exc:
        print(f"rotation refused: {exc}")
        return 1
    store.save(trace)
    print(f"rotated {trace.id} to a new signing key "
          f"(old key no longer verifies the chain)")
    return 0


def cmd_scan_tool(args: argparse.Namespace) -> int:
    from .toolscan import scan

    text = Path(args.file).read_text(encoding="utf-8")
    result = scan(text)
    print(result.summary())
    return 0 if result.is_clean else 1


def cmd_counterfactual(args: argparse.Namespace) -> int:
    from .counterfactual import counterfactual

    store = TraceStore(args.store)
    trace = _load_trace(args.trace, store)
    report = counterfactual(trace)
    print(report.summary())
    return 0


def cmd_drift(args: argparse.Namespace) -> int:
    from .drift import detect_drift

    store = TraceStore(args.store)
    traces = sorted(store.list_traces(), key=lambda t: t.created_at)
    split_at = int(len(traces) * args.baseline_ratio)
    baseline, current = traces[:split_at], traces[split_at:]
    if not baseline or not current:
        print("need traces in both windows "
              "(baseline = oldest, current = newest)")
        return 1
    report = detect_drift(baseline, current)
    print(report.summary())
    return 0


def _print_query_stats(found, stats_json: bool) -> int:
    from .query import summarize

    stats = summarize(found)
    if stats_json:
        print(json.dumps(stats, indent=2))
        return 0
    print(f"count {stats['count']}  "
          f"ok {stats['success']}  failed {stats['failed']}  "
          f"failure rate {stats['failure_rate'] * 100:.1f}%")
    if stats["modes"]:
        modes = ", ".join(f"{m} x{c}" for m, c in stats["modes"].items())
        print(f"modes: {modes}")
    print(f"mean steps {stats['mean_steps']}  "
          f"mean tokens {stats['mean_tokens']}")
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    from .query import QueryError, select

    store = TraceStore(args.store)
    try:
        found = select(store.list_traces(), args.expression)
    except QueryError as exc:
        raise SystemExit(f"error: {exc}") from exc
    if getattr(args, "stats", False):
        return _print_query_stats(found, stats_json=bool(args.json))
    if getattr(args, "json", None):
        print(json.dumps([t.to_dict() for t in found],
                         indent=2, default=str))
        return 0
    for trace in found:
        mark = "ok " if trace.success else "FAIL"
        task = " ".join((trace.task or "").split())[:52]
        print(f"{trace.id}  {mark}  {len(trace.steps):>3} steps  {task}")
    print(f"{len(found)} matching trace(s)")
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    from .diff import Op
    from .diff import diff as trace_diff

    store = TraceStore(args.store)
    trace_a = _load_trace(args.trace, store)
    trace_b = _load_trace(args.other, store)
    result = trace_diff(trace_a, trace_b)
    if getattr(args, "json", None):
        counts = result.counts
        print(json.dumps({
            "a_id": result.a_id, "b_id": result.b_id,
            "similarity": round(result.similarity, 3),
            "equal": counts[Op.EQUAL], "mutated": counts[Op.MUTATED],
            "deleted": counts[Op.DELETED],
            "inserted": counts[Op.INSERTED],
            "entries": [{"op": e.symbol,
                         "a_index": e.a_index, "b_index": e.b_index,
                         "a_tool": e.a_tool, "b_tool": e.b_tool,
                         "similarity": e.similarity,
                         "detail": e.detail}
                        for e in result.entries
                        if e.op != Op.EQUAL],
        }, indent=2))
        return 0
    print(result.summary())
    return 0


def cmd_bisect(args: argparse.Namespace) -> int:
    """Locate the first material divergence between two runs."""
    from .diff import diff as trace_diff
    from .diff import first_fault

    store = TraceStore(args.store)
    trace_a = _load_trace(args.trace, store)
    trace_b = _load_trace(args.other, store)
    td = trace_diff(trace_a, trace_b)
    fault = first_fault(td, floor=args.floor)
    ranked = td.divergences(limit=5)
    if getattr(args, "json", None):
        print(json.dumps({
            "a_id": td.a_id, "b_id": td.b_id,
            "similarity": round(td.similarity, 3),
            "floor": args.floor,
            "first_fault": None if fault is None else {
                "op": fault.symbol,
                "a_index": fault.a_index, "b_index": fault.b_index,
                "a_tool": fault.a_tool, "b_tool": fault.b_tool,
                "similarity": fault.similarity,
                "detail": fault.detail,
            },
            "divergences": [{"op": e.symbol,
                             "a_index": e.a_index, "b_index": e.b_index,
                             "similarity": e.similarity,
                             "detail": e.detail}
                            for e in ranked],
        }, indent=2))
        return 0 if fault else 1
    print(f"bisect {td.a_id} vs {td.b_id} - "
          f"similarity {td.similarity:.0%}")
    if fault is None:
        print(f"no material divergence below floor {args.floor:g}")
        return 1
    step = fault.a_index if fault.a_index is not None else fault.b_index
    print(f"first material divergence at step #{step} "
          f"(similarity {fault.similarity:.2f}):")
    print(f"  {fault.render()}")
    print("worst divergences (ranked by similarity):")
    for entry in ranked:
        print(f"  {entry.render()}")
    return 0


def cmd_repair(args: argparse.Namespace) -> int:
    from .repair import plan_repair

    store = TraceStore(args.store)
    trace = _load_trace(args.trace, store)
    result = plan_repair(trace)
    print(result.summary())
    if result.repaired_trace is not None and args.apply:
        out = store.directory / f"{trace.id}.repaired.json"
        out.write_text(result.repaired_trace.to_json(), encoding="utf-8")
        print(f"repaired trace written: {out}")
    return 0


def _parse_labels(pairs):
    """--label k=v strings -> dict; the renderers need real labels."""
    if not pairs:
        return None
    out = {}
    for pair in pairs:
        key, eq, value = pair.partition("=")
        if not key or not eq:
            raise SystemExit(f"error: --label expects k=v, got {pair!r}")
        out[key] = value
    return out


def cmd_metrics(args: argparse.Namespace) -> int:
    from .cluster import agent_scorecard, store_stats
    from .metrics import render_agent_prometheus, render_prometheus

    store = TraceStore(args.store)
    traces = store.list_traces()
    stats = store_stats(traces)
    if args.prometheus and getattr(args, "by_agent", False):
        rows = agent_scorecard(traces)
        print(render_agent_prometheus(rows,
                                      extra_labels=_parse_labels(args.label)))
        return 0
    if args.prometheus:
        print(render_prometheus(stats, extra_labels=_parse_labels(args.label)))
        return 0
    print(stats.summary())
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    from .integrity import load_key

    store = TraceStore(args.store)
    if getattr(args, "all", None):
        return _verify_all(store, key=load_key(args.key_file),
                           as_json=getattr(args, "json", False),
                           since_days=getattr(args, "since", None),
                           strict=getattr(args, "strict", False),
                           quiet=getattr(args, "quiet", False))
    if not args.trace:
        print("provide a trace id, or use --all")
        return 2
    return _verify_one(args, store, load_key(args.key_file))


def _verify_one(args: argparse.Namespace, store, key) -> int:
    from .integrity import verify
    from .ledger import audit_rollback, verify_ledger

    trace = _load_trace(args.trace, store)
    result = verify(trace, key=key)
    if result.verdict == "unsigned":
        print("unsigned: trace carries no integrity block "
              "(recorded before v0.3.1)")
        return 2
    if result.verdict == "keyed":
        print(f"KEYED: {result.detail}")
        return 3
    if not result.intact:
        print(f"TAMPERED: {result.detail}")
        print(f"  expected chain final: {result.expected_final}")
        print(f"  actual chain final:   {result.actual_final}")
        return 1

    kind = "HMAC-authenticated" if key else "intact"
    print(f"{kind}: {result.detail}")
    print(f"  chain final: {result.actual_final}")

    rollback = audit_rollback(trace, store.directory)
    if rollback:
        root = result.actual_final or "?"
        print(f"ROLLED-BACK: an older signed state of this trace is in "
              f"the evidence ledger ({root[:12]}…); newer "
              f"saves were recorded afterwards — the file was rolled "
              f"back, the hashes are valid but the state is stale")
        return 4
    ledger_check = verify_ledger(store.directory)
    if ledger_check.entries and not ledger_check.intact:
        print(f"LEDGER-BROKEN: {ledger_check.detail}")
        return 5
    return 0


def cmd_merge(args: argparse.Namespace) -> int:
    from .merge import merge_store

    store = TraceStore(args.store)
    report = merge_store(Path(args.source), store,
                         on_conflict=args.on_conflict)
    print(report.summary())
    return 0


def _print_fleet(summaries) -> None:
    for s in summaries:
        flag = "" if s.ledger_intact is not False else "  [LEDGER BROKEN]"
        print(f"{s.name}: {s.traces} traces, "
              f"failure rate {s.failure_rate:.0%}{flag}")


def _fleet_notify(summaries, url: str) -> None:
    from .fleet import notify_webhook
    from .integrity import load_key

    try:
        status = notify_webhook(summaries, url, signing_key=load_key())
        print(f"webhook notified: HTTP {status}")
    except RuntimeError as exc:
        print(f"webhook failed: {exc}", file=sys.stderr)


def cmd_mcp(args: argparse.Namespace) -> int:
    from .mcp_server import cmd_mcp as _serve_mcp

    return _serve_mcp(args)


def _fleet_watch(args: argparse.Namespace, stores) -> int:
    import signal

    from .fleet import watch_fleet

    def _stop(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _stop)
    try:
        written = watch_fleet(
            stores, Path(args.digest_dir), float(args.watch),
            keep_days=args.keep_days,
            iterations=getattr(args, "iterations", None),
            top_agents=getattr(args, "top_agents", 3))
    except KeyboardInterrupt:
        print("watch stopped")
        return 0
    print(f"wrote {written} snapshot(s) to {args.digest_dir}")
    return 0


def _fleet_trend(args: argparse.Namespace) -> int:
    from .fleet import (
        agent_trend_days,
        render_trend,
        summarize_agent_trend,
        summarize_trend,
        trend_days,
    )
    from .report import TREND_LABELS, render_sparkline

    agent = getattr(args, "agent", None)
    days = trend_days(Path(args.digest_dir))
    if agent:
        agent_days = agent_trend_days(Path(args.digest_dir), agent)
        agent_summary = summarize_agent_trend(agent_days)
        verdict, slope = agent_summary["verdict"], agent_summary["slope"]
        spark = render_sparkline(
            [d["failed_traces"] / d["traces"] * 100
             for d in agent_days if d["traces"]],
            width=180, height=34)
        _, trend_label = TREND_LABELS[verdict]
        if getattr(args, "json", False):
            print(json.dumps({"agent": agent, "days": agent_days,
                              "verdict": verdict, "slope": slope},
                             indent=2))
            return 0
        print(f"agent trend - {agent} - {len(agent_days)} day(s)")
        for d in agent_days:
            rate = f"{d['failed_traces'] / d['traces']:.0%}" \
                if d["traces"] else "-"
            print(f"  {d['day']}: {d['steps']:>5} steps, "
                  f"{d['errors']:>3} errors, "
                  f"{d['failed_traces']:>3}/{d['traces']:<3} failed "
                  f"({rate})")
        print(f"  sparkline: {spark}")
        print(f"  verdict: {trend_label} (slope {slope})")
        if getattr(args, "fail_on_worsening", False) \
                and verdict == "worsening":
            print(f"agent trend is worsening: {agent}", file=sys.stderr)
            return 1
        return 0
    summary = summarize_trend(days)
    if getattr(args, "json", False):
        print(json.dumps(summary, indent=2))
    else:
        print(render_trend(summary))
    if getattr(args, "fail_on_worsening", False) \
            and summary["verdict"] == "worsening":
        print("fleet trend is worsening", file=sys.stderr)
        return 1
    return 0


def _fleet_survey(args: argparse.Namespace) -> int:
    from .fleet import render_fleet_html, survey

    summaries = survey([Path(d) for d in args.stores],
                       top_agents=getattr(args, "top_agents", 3))
    trend_summary = None
    digest_dir = getattr(args, "digest_dir", None)
    if args.fleet_html and digest_dir and Path(digest_dir).is_dir():
        from .fleet import summarize_trend, trend_days

        trend_summary = summarize_trend(trend_days(Path(digest_dir)))
    if getattr(args, "json", False):
        from .fleet import webhook_payload

        print(json.dumps(webhook_payload(summaries), indent=2))
        return 0
    _print_fleet(summaries)
    if args.fleet_html:
        out = Path(args.fleet_html)
        out.write_text(render_fleet_html(summaries,
                                         trend_summary=trend_summary),
                       encoding="utf-8")
        print(f"wrote fleet dashboard: {out}")
    if getattr(args, "webhook", None):
        _fleet_notify(summaries, args.webhook)
    if args.fail_on_worsening:
        worsening = [s.name for s in summaries if s.worsening]
        if worsening:
            print(f"FAIL: worsening failure-rate trend in: "
                  f"{', '.join(worsening)}")
            return 1
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    from .doctor import doctor, fix_hygiene

    report = doctor(Path(args.store),
                    Path(args.digest_dir) if args.digest_dir else None)
    if getattr(args, "fix", False):
        removed = fix_hygiene(Path(args.store), report)
        report.stale_locks = [n for n in report.stale_locks
                              if n not in removed]
        report.temp_files = [n for n in report.temp_files
                             if n not in removed]
        # human-readable note on stderr keeps --json stdout parseable
        print(f"removed {len(removed)} hygiene artifact(s)",
              file=sys.stderr)
    if getattr(args, "json", False):
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(report.render())
    return 0 if report.healthy else 1


def cmd_fleet(args: argparse.Namespace) -> int:
    stores = [Path(d) for d in args.stores]
    if getattr(args, "watch", None):
        return _fleet_watch(args, stores)
    if getattr(args, "trend", False):
        return _fleet_trend(args)
    return _fleet_survey(args)


def cmd_anomalies(args: argparse.Namespace) -> int:
    from .anomaly import detect_latency_anomalies, summarize_anomalies

    store = TraceStore(args.store)
    trace = _load_trace(args.trace, store)
    anomalies = detect_latency_anomalies(trace, threshold=args.threshold)
    print(summarize_anomalies(anomalies))
    return 0 if not anomalies else 1


def _audit_row(store, trace, key, counts: dict) -> dict:
    """Verify one trace and tally its verdict into counts."""
    from .integrity import verify
    from .ledger import audit_rollback

    result = verify(trace, key=key)
    verdict = result.verdict
    if verdict == "intact" and audit_rollback(trace, store.directory):
        verdict = "rolled-back"
    counts[verdict if verdict in counts else "problem"] += 1
    return {"trace_id": trace.id, "verdict": verdict,
            "detail": result.detail}


def _verify_all(store, key, as_json: bool = False,
                since_days: Optional[int] = None,
                strict: bool = False, quiet: bool = False) -> int:
    """Batch integrity audit; exit 1 when any trace fails.

    ``strict`` also fails on unsigned and keyed-locked records — for
    cron/CI gates where "every record must carry verifiable evidence"
    is the policy, not just "nothing is broken".
    """
    import json as _json

    from .ledger import verify_ledger

    counts = {"intact": 0, "unsigned": 0, "keyed": 0, "problem": 0}
    rows = [_audit_row(store, trace, key, counts)
            for trace in store.list_traces(since_days=since_days)]
    ledger_check = verify_ledger(store.directory)
    ledger_broken = bool(ledger_check.entries) and not ledger_check.intact
    if ledger_broken:
        counts["problem"] += 1
    if as_json:
        print(_json.dumps({
            "summary": counts, "ledger_broken": ledger_broken,
            "ledger_detail": ledger_check.detail,
            "strict": strict,
            "traces": rows,
        }, indent=2))
        return 1 if _verify_fails(counts, strict) else 0
    if not quiet:
        for row in rows:
            flag = {"intact": "", "unsigned": " (unsigned)",
                    "keyed": " (keyed, no key)"}.get(
                        row["verdict"], " <-- " + row["verdict"])
            print(f"{row['trace_id']}: {row['verdict']}{flag}")
    if ledger_broken:
        print(f"LEDGER BROKEN: {ledger_check.detail}")
    print(f"\n{counts['intact']} intact · {counts['unsigned']} unsigned · "
          f"{counts['keyed']} keyed (locked) · {counts['problem']} failed"
          + ("  [strict]" if strict else ""))
    return 1 if _verify_fails(counts, strict) else 0


def _verify_fails(counts: dict, strict: bool) -> bool:
    """Strict mode treats unsigned/keyed-locked records as failures."""
    if strict:
        return bool(counts["problem"] or counts["unsigned"]
                    or counts["keyed"])
    return bool(counts["problem"])


def cmd_convert_mast(args: argparse.Namespace) -> int:
    from .mastdata import convert_mast

    stats = convert_mast(Path(args.source), Path(args.output),
                         multi_label=getattr(args, "multi_label", False))
    print(stats.summary())
    for mode_id, count in sorted(stats.labels.items()):
        print(f"  {mode_id}: {count} traces")
    print(f"wrote {args.output}")
    return 0 if stats.converted else 1


def cmd_clean(args: argparse.Namespace) -> int:
    store = TraceStore(args.store)
    removed = store.clean(keep_days=args.keep_days)
    print(f"removed {removed} traces older than {args.keep_days} days")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    from .cluster import store_stats

    store = TraceStore(args.store)
    traces = store.list_traces(since_days=getattr(args, "since", None))
    if getattr(args, "by_agent", False):
        from .cluster import agent_scorecard

        rows = agent_scorecard(
            traces, min_failed=getattr(args, "min_failed", None))
        if args.json:
            print(json.dumps(rows, indent=2))
            return 0
        print(f"  {'agent':<20} {'traces':>6} {'steps':>6} "
              f"{'tools':>6} {'tokens':>7} {'errors':>6} "
              f"{'failed':>6} {'rate':>6}")
        for r in rows:
            print(f"  {r['agent']:<20} {r['traces']:>6} {r['steps']:>6} "
                  f"{r['tool_calls']:>6} {r['tokens']:>7} {r['errors']:>6} "
                  f"{r['failed_traces']:>6} {r['failure_rate']:>5.0%}")
        return 0
    stats = store_stats(traces)
    if args.trend:
        from .cluster import trend

        buckets = trend(traces, bucket_days=args.trend_bucket_days)
        if args.json:
            print(json.dumps(buckets, indent=2))
            return 0
        rates = [b["failure_rate"] for b in buckets]
        from .cluster import sparkline

        print(f"  failure-rate sparkline: {sparkline(rates)}")
        for b in buckets:
            print(f"  {b['bucket_start']}: {b['total']} runs, "
                  f"{b['failed']} failed ({b['failure_rate']:.0%})")
        return 0
    if args.json:
        print(json.dumps({
            "traces": stats.traces,
            "failures": stats.failures,
            "failure_rate": round(stats.failure_rate, 3),
            "avg_steps": round(stats.avg_steps, 1),
            "modes": stats.mode_counts,
        }, indent=2))
        return 0
    print(stats.summary())
    return 0


def cmd_attribute(args: argparse.Namespace) -> int:
    from .sarif import to_sarif

    store = TraceStore(args.store)
    if args.sarif:
        pairs = [(t, attribute(t, use_judge=args.judge))
                 for t in store.list_traces()]
        out = Path(args.sarif)
        out.write_text(json.dumps(to_sarif([r for _, r in pairs]),
                                  indent=2), encoding="utf-8")
        print(f"wrote SARIF over {len(pairs)} traces: {out}")
        return 0
    if args.all:
        results = []
        for trace in store.list_traces(since_days=args.since):
            report = attribute(trace, use_judge=args.judge,
                               min_confidence=args.min_confidence)
            entry = report.to_dict()
            entry["trace"] = {"id": trace.id, "task": trace.task,
                              "success": trace.success,
                              "steps": len(trace.steps)}
            results.append(entry)
        print(json.dumps(results, indent=2))
        return 0
    trace = _load_trace(args.trace, store)
    report = attribute(trace, use_judge=args.judge,
                       min_confidence=args.min_confidence)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        note = "" if report.judge_used or not args.judge else \
            "(judge requested but unavailable — rules only)"
        _print_report(report, note, top=getattr(args, "top", 0))
    if getattr(args, "explain", None):
        from .attributor import explain_fusion

        print(explain_fusion(report.detections))
    return 0


def cmd_cluster(args: argparse.Namespace) -> int:
    from .cluster import agent_scorecard, cluster

    store = TraceStore(args.store)
    traces = store.list_traces(since_days=getattr(args, "since", None))
    if args.last:
        traces = traces[-args.last:]
    if getattr(args, "by_agent", False):
        rows = [r for r in agent_scorecard(traces)
                if r["failed_traces"] >= args.min_size]
        if args.json:
            print(json.dumps(rows, indent=2))
            return 0
        if not rows:
            print("no recidivist agents at this threshold")
            return 0
        print(f"recidivist agents (in >= {args.min_size} failed "
              "traces):")
        for r in rows:
            print(f"  {r['agent']:<24} {r['failed_traces']:>3} failed / "
                  f"{r['traces']:>3} touched  ({r['failure_rate']:.0%}), "
                  f"{r['steps']} steps, {r['errors']} errors")
        return 0
    if args.json:
        report = cluster(traces)
        payload = {
            "traces_scanned": report.traces_scanned,
            "failures_found": report.failures_found,
            "clusters": [
                {"mode_id": c.mode_id, "size": c.size, "tools": list(c.tools),
                 "example_task": c.example_task}
                for c in report.clusters
            ],
        }
        print(json.dumps(payload, indent=2))
        return 0
    print(cluster(traces).summary(min_size=args.min_size))
    return 0


def cmd_curve(args: argparse.Namespace) -> int:
    from .curve import budget_curve, render_curve_html, success_vs_tokens

    store = TraceStore(args.store)
    trace = _load_trace(args.trace, store)
    budgets = None
    if args.budgets:
        budgets = [int(b) for b in args.budgets.split(",") if b.strip()]
    curve = budget_curve(trace, budgets=budgets)
    scatter = success_vs_tokens(store.list_traces()) if args.scatter else None
    out = Path(args.output) if args.output else store.directory / f"{trace.id}.curve.html"
    out.write_text(render_curve_html(curve, scatter), encoding="utf-8")
    print(f"wrote {out}")
    for p_ in curve.points:
        print(f"  budget {p_.budget:>6} -> tokens {p_.tokens_used:>6}, "
              f"recall {p_.recall:.0%}")
    return 0


def cmd_distill(args: argparse.Namespace) -> int:
    from .distill import export_sft, rules_labeler, teacher_labeler

    store = TraceStore(args.store)
    traces = store.list_traces()
    if args.teacher:
        labeler = teacher_labeler(args.teacher)
        source = f"teacher {args.teacher}"
    else:
        labeler = rules_labeler()
        source = "rule detectors"
    stats = export_sft(traces, Path(args.output), labeler)
    print(f"labeled {stats['labeled']} traces via {source} "
          f"({stats['skipped']} skipped, too unsure)")
    for mode_id, count in sorted(stats["modes"].items()):
        print(f"  {mode_id}: {count}")
    print(f"training data: {args.output} "
          f"(fine-tune, then APPROXIMATELY_JUDGE_MODEL=<model> "
          f"approximately attribute <trace> --judge)")
    return 0


def cmd_export_dataset(args: argparse.Namespace) -> int:
    from .distill import export_dataset, rules_labeler, teacher_labeler

    store = TraceStore(args.store)
    traces = store.list_traces()
    if args.teacher:
        labeler = teacher_labeler(args.teacher)
        source = f"teacher {args.teacher}"
    else:
        labeler = rules_labeler()
        source = "rule detectors"
    stats = export_dataset(traces, Path(args.output), labeler)
    print(f"wrote {stats['written']} labeled traces to {args.output} "
          f"({stats['skipped']} skipped, too unsure) via {source}")
    return 0


def _benchmark_multi(labeled, args: argparse.Namespace) -> int:
    from .distill import evaluate_multi, render_leaderboard_html

    pairs = []
    for trace, record_label in labeled:
        labels = record_label if isinstance(record_label, list) \
            else [record_label]
        pairs.append((trace, labels))
    multi = evaluate_multi(pairs)
    source = "rule detectors (set-based)"
    n = len(pairs)
    print(f"labeled {n} multi-label traces · predictor: {source}")
    print(f"sample-averaged precision {multi.sample_precision:.2f}, "
          f"recall {multi.sample_recall:.2f}, F1 {multi.macro_f1:.2f}")
    for mode_id, m in sorted(multi.per_mode.items()):
        print(f"  {mode_id:<7} P {m['precision']:.2f} "
              f"[{m['precision_ci'][0]:.2f},{m['precision_ci'][1]:.2f}] "
              f"R {m['recall']:.2f} "
              f"[{m['recall_ci'][0]:.2f},{m['recall_ci'][1]:.2f}] "
              f"F1 {m['f1']:.2f} "
              f"(tp {m['tp']} fp {m['fp']} fn {m['fn']})")
    if args.html:
        out = Path(args.html)
        out.write_text(
            render_leaderboard_html(multi, source, args.dataset, n),
            encoding="utf-8")
        print(f"wrote leaderboard: {out}")
    return 0


def cmd_benchmark(args: argparse.Namespace) -> int:
    from .distill import evaluate, load_dataset, rules_labeler, teacher_labeler

    labeled = load_dataset(Path(args.dataset), fmt=args.format)
    if not labeled:
        print("no labeled records found")
        return 1
    if args.multi_label:
        return _benchmark_multi(labeled, args)

    if args.judge:
        labeler = teacher_labeler(args.judge_model or "gpt-4o-mini")
        source = f"judge {args.judge_model or 'gpt-4o-mini'}"
    else:
        labeler = rules_labeler()
        source = "rule detectors"
    result = evaluate(labeled, labeler)
    print(f"labeled {len(labeled)} traces · predictor: {source}")
    print(result.summary())
    if args.html:
        from .distill import render_leaderboard_html

        out = Path(args.html)
        out.write_text(
            render_leaderboard_html(result, source, args.dataset,
                                    len(labeled)),
            encoding="utf-8",
        )
        print(f"wrote leaderboard: {out}")
    return 0


def cmd_new(args: argparse.Namespace) -> int:
    from .scaffold import scaffold

    target = scaffold(args.name, base=Path.cwd())
    print(f"created {target}/")
    print(f"  {args.name}/agent.py                    <- your agent, recorder wired")
    print(f"  {args.name}/test_agent_regressions.py  <- guards")
    print(f"  {args.name}/README.md")
    print("next: pip install approximately && python "
          f"{args.name}/agent.py")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="approximately",
        description="The flight recorder & postmortem toolkit for AI agents.",
    )
    parser.add_argument("--version", action="version",
                        version=f"approximately {__version__}")
    parser.add_argument("--store", help="trace store directory "
                                        "(default ~/.approximately/traces)")
    sub = parser.add_subparsers(dest="command", required=True)

    # --store is accepted both before and after the subcommand.
    # SUPPRESS default: without it the subparser's None default clobbers
    # the top-level value when --store precedes the subcommand.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--store", default=argparse.SUPPRESS,
                        help=argparse.SUPPRESS)

    p = sub.add_parser("demo", parents=[common],
                       help="run the built-in failing agent (30s tour)")
    p.add_argument("--open", action="store_true", help="open the HTML report")
    p.add_argument("--context-budget", type=int, default=60,
                   help="token budget for the context-runtime demo (default 60)")
    p.add_argument("--scenario",
                   choices=["booking", "multi-agent", "loop",
                            "verification"],
                   default="booking",
                   help="demo scenario (default booking)")
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("attribute", parents=[common],
                       help="attribute a failure on a trace")
    p.add_argument("trace", nargs="?",
                   help="trace id or path to trace JSON (required unless --all)")
    p.add_argument("--judge", action="store_true",
                   help="add the LLM judge verdict (needs openai + API key)")
    p.add_argument("--json", action="store_true", help="emit JSON")
    p.add_argument("--top", type=int, default=0, metavar="N",
                   help="also print up to N runner-up hypotheses the "
                        "detectors fired for")
    p.add_argument("--min-confidence", type=float, default=None,
                   metavar="X",
                   help="raise the per-detection admission floor above "
                        "the built-in 0.5 (noisy environments); never "
                        "lowers it")
    p.add_argument("--all", action="store_true",
                   help="attribute every trace in the store (JSON output)")
    p.add_argument("--sarif", help="write attribution as SARIF 2.1.0 "
                                   "(GitHub code scanning)")
    p.add_argument("--since", type=int, metavar="DAYS",
                   help="with --all: only traces created in the last "
                        "DAYS days")
    p.add_argument("--explain", action="store_true",
                   help="print the fusion arithmetic: prior log-odds and "
                        "LLR per detection")
    p.set_defaults(func=cmd_attribute)

    p = sub.add_parser("replay", parents=[common],
                       help="replay a trace through an executor")
    p.add_argument("trace")
    p.add_argument("--executor", required=True,
                   help="executor as 'package.module:func' taking a Step")
    p.add_argument("--patched",
                   help="A/B: a second executor to compare against --executor")
    p.add_argument("--html", help="also write a self-contained HTML A/B "
                                  "page to this path")
    p.add_argument("--threshold", type=float, default=0.85,
                   help="step-result similarity floor (default 0.85)")
    p.set_defaults(func=cmd_replay)

    p = sub.add_parser("test", parents=[common],
                       help="generate a pytest regression file")
    p.add_argument("trace")
    p.add_argument("-o", "--output", help="output test path")
    p.add_argument("--budget", type=int,
                   help="also emit a context budget regression guard")
    p.add_argument("--min-recall", type=float, default=0.8,
                   help="required effective recall for the budget guard "
                        "(default 0.8)")
    p.set_defaults(func=cmd_test)

    p = sub.add_parser("report", parents=[common],
                       help="render the HTML postmortem report")
    p.add_argument("trace", nargs="?", help="trace id or path (required unless --all)")
    p.add_argument("--all", action="store_true",
                   help="render an index page over every trace in the store")
    p.add_argument("-o", "--output", help="output HTML path")
    p.add_argument("--mermaid", help="also write a mermaid sequence "
                                     "diagram of the trace to this path "
                                     "(pastes into GitHub markdown)")
    p.add_argument("--judge", action="store_true")
    p.add_argument("--markdown", action="store_true",
                   help="write the postmortem as issue-ready Markdown "
                        "instead of HTML")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("context", parents=[common],
                       help="forecast a token budget against a trace")
    p.add_argument("trace")
    p.add_argument("--budget", type=int, default=400,
                   help="token budget to simulate (default 400)")
    p.add_argument("--facts", help="JSON file mapping fact keys -> expected substrings "
                                   "(default: one fact per tool result)")
    p.set_defaults(func=cmd_context)

    p = sub.add_parser("new", help="scaffold an instrumented agent project")
    p.add_argument("name", help="project directory name")
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("similar", parents=[common],
                       help="rank store traces by alignment similarity "
                            "to a trace")
    p.add_argument("trace")
    p.add_argument("--top", type=int, default=5)
    p.set_defaults(func=cmd_similar)

    p = sub.add_parser("predict", parents=[common],
                       help="failure-probability early warning from "
                            "store history")
    p.add_argument("trace")
    p.set_defaults(func=cmd_predict)

    p = sub.add_parser("optimize", parents=[common],
                       help="binary-search the smallest context budget "
                            "that keeps recall >= target")
    p.add_argument("trace")
    p.add_argument("--min-recall", type=float, default=1.0,
                   help="required effective recall (default 1.0)")
    p.set_defaults(func=cmd_optimize)

    p = sub.add_parser("calibrate", parents=[common],
                       help="fit temperature + conformal threshold on a "
                            "labeled dataset; report held-out coverage/ECE")
    p.add_argument("dataset", help="labeled JSONL (approx format)")
    p.add_argument("--format", choices=["approx", "mast"], default="approx")
    p.add_argument("--alpha", type=float, default=0.1,
                   help="miscoverage level (default 0.1 = 90%% coverage)")
    p.set_defaults(func=cmd_calibrate)

    p = sub.add_parser("rotate", parents=[common],
                       help="re-key a signed trace (old key must verify)")
    p.add_argument("trace")
    p.add_argument("--old-key-file", help="current signing key")
    p.add_argument("--new-key-file", required=True, help="new signing key")
    p.set_defaults(func=cmd_rotate)

    p = sub.add_parser("scan-tool", parents=[common],
                       help="scan an MCP tool description for poisoning")
    p.add_argument("file", help="tool description (text) to scan")
    p.set_defaults(func=cmd_scan_tool)

    p = sub.add_parser("counterfactual", parents=[common],
                       help="do(step=∅) experiments: root causes vs symptoms")
    p.add_argument("trace")
    p.set_defaults(func=cmd_counterfactual)

    p = sub.add_parser("drift", parents=[common],
                       help="PSI behavior-drift between the oldest and "
                            "newest traces")
    p.add_argument("--baseline-ratio", type=float, default=0.5,
                   help="share of oldest traces used as baseline (default 0.5)")
    p.set_defaults(func=cmd_drift)

    p = sub.add_parser("diff", parents=[common],
                       help="git-style diff of two runs (failed vs last "
                            "success is the classic use)")
    p.add_argument("trace")
    p.add_argument("other", help="the trace to compare against")
    p.add_argument("--json", action="store_true",
                   help="emit counts plus every differing entry (with "
                        "per-entry similarity) as JSON")
    p.set_defaults(func=cmd_diff)

    p = sub.add_parser("bisect", parents=[common],
                       help="first material divergence between two runs "
                            "(failed vs last success is the classic use)")
    p.add_argument("trace")
    p.add_argument("other", help="the trace to compare against")
    p.add_argument("--floor", type=float, default=0.8,
                   help="mutations with similarity >= FLOOR count as "
                        "noise, not faults (default 0.8)")
    p.add_argument("--json", action="store_true",
                   help="emit the first fault plus ranked divergences "
                        "as JSON")
    p.set_defaults(func=cmd_bisect)

    p = sub.add_parser("query", parents=[common],
                       help="select traces with an expression, e.g. "
                            "\"success == false and task contains 'fix'\"")
    p.add_argument("expression")
    p.add_argument("--json", action="store_true",
                   help="emit matching trace records as JSON")
    p.add_argument("--stats", action="store_true",
                   help="aggregate the selection instead of listing it: "
                        "counts, failure rate, mode totals, means")
    p.set_defaults(func=cmd_query)

    p = sub.add_parser("repair", parents=[common],
                       help="search the minimal intervention set that "
                            "clears attribution (prescription validation)")
    p.add_argument("trace")
    p.add_argument("--apply", action="store_true",
                   help="write the repaired trace into the store")
    p.set_defaults(func=cmd_repair)

    p = sub.add_parser("metrics", parents=[common],
                       help="store statistics (Prometheus format with "
                            "--prometheus)")
    p.add_argument("--prometheus", action="store_true",
                   help="emit Prometheus text exposition format")
    p.add_argument("--by-agent", action="store_true",
                   help="with --prometheus: per-agent counters instead "
                        "of store totals")
    p.add_argument("--label", action="append",
                   help="extra label k=v for the --prometheus output")
    p.set_defaults(func=cmd_metrics)

    p = sub.add_parser("verify", parents=[common],
                       help="verify the tamper-evident hash chain of a trace")
    p.add_argument("trace", nargs="?", help="trace id (required unless --all)")
    p.add_argument("--key-file",
                   help="signing key file for HMAC-keyed traces")
    p.add_argument("--all", action="store_true",
                   help="verify every trace in the store (exit 1 on any "
                        "TAMPERED or rolled-back trace; then trace id is "
                        "omitted)")
    p.add_argument("--json", action="store_true",
                   help="emit machine-readable audit JSON (with --all)")
    p.add_argument("--since", type=int, metavar="DAYS",
                   help="with --all: only traces created in the last "
                        "DAYS days")
    p.add_argument("--strict", action="store_true",
                   help="with --all: unsigned and keyed-locked records "
                        "also fail the audit (cron/CI policy gate)")
    p.add_argument("--quiet", action="store_true",
                   help="with --all: summary line only, no per-trace rows")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("convert-mast",
                       help="convert MAST-Data annotations to labeled "
                            "benchmark JSONL")
    p.add_argument("source", help="MAST-Data checkout directory")
    p.add_argument("output", help="output JSONL path")
    p.add_argument("--multi-label", action="store_true",
                   help="emit a labels SET per record (for set-based "
                        "evaluation) instead of a single label")
    p.set_defaults(func=cmd_convert_mast)

    p = sub.add_parser("fleet", help="aggregate several stores into one "
                                     "dashboard page")
    p.add_argument("stores", nargs="+", help="store directories to survey")
    p.add_argument("--fleet-html", help="also write a self-contained HTML "
                                        "dashboard to this path")
    p.add_argument("--json", action="store_true",
                   help="emit machine-readable fleet JSON instead of text")
    p.add_argument("--fail-on-worsening", action="store_true",
                   help="exit 1 when any store's failure-rate trend is "
                        "worsening (CI gate)")
    p.add_argument("--webhook", help="POST a JSON fleet summary to this "
                                     "URL (HMAC-signed when "
                                     "APPROXIMATELY_SIGNING_KEY is set)")
    p.add_argument("--watch", type=float,
                   help="poll the fleet every SECONDS seconds, appending "
                        "a JSONL snapshot to --digest-dir each cycle "
                        "(Ctrl-C to stop)")
    p.add_argument("--digest-dir",
                   help="directory for watch-loop JSONL snapshots "
                        "(required with --watch)")
    p.add_argument("--keep-days", type=int, default=30,
                   help="watch loop: delete digest files older than "
                        "DAYS days (default 30)")
    p.add_argument("--iterations", type=int,
                   help="watch loop: stop after N snapshots instead of "
                        "running until interrupted (cron-friendly)")
    p.add_argument("--trend", action="store_true",
                   help="summarize the digest history in --digest-dir: "
                        "per-day fleet state, sparkline, verdict")
    p.add_argument("--top-agents", type=int, default=3, metavar="N",
                   help="busiest named agents kept per store in "
                        "digest snapshots and dashboards (default 3; "
                        "fleet --trend --agent can only see agents "
                        "inside this window)")
    p.add_argument("--agent", metavar="NAME",
                   help="with --trend: per-day analytics for one named "
                        "agent (observed while among a store's top-3 "
                        "busiest named agents in the digest snapshots)")
    p.set_defaults(func=cmd_fleet)

    p = sub.add_parser("mcp", parents=[common],
                       help="serve the toolkit as an MCP (Model Context "
                            "Protocol) stdio server — JSON-RPC 2.0, "
                            "zero dependencies")
    p.set_defaults(func=cmd_mcp)

    p = sub.add_parser("doctor", parents=[common],
                       help="health check: parseable records, ledger "
                            "intact, stale locks, digest gaps")
    p.add_argument("--digest-dir",
                   help="also report monitoring gaps and torn lines in "
                        "this digest directory")
    p.add_argument("--fix", action="store_true",
                   help="remove stale writer locks and leftover temp "
                        "files (never record data, ledger, or digests)")
    p.add_argument("--json", action="store_true",
                   help="emit the full report as JSON")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("anomalies", parents=[common],
                       help="robust latency anomalies (median/MAD z-score)")
    p.add_argument("trace", help="trace id (or 'latest')")
    p.add_argument("--threshold", type=float, default=3.5,
                   help="modified z-score threshold (default 3.5, "
                        "Iglewicz & Hoaglin)")
    p.set_defaults(func=cmd_anomalies)

    p = sub.add_parser("merge", parents=[common],
                       help="import another store's traces into this one")
    p.add_argument("source", help="source store directory")
    p.add_argument("--on-conflict", choices=["skip", "replace", "rename"],
                   default="skip",
                   help="same-id policy (default: skip, target wins)")
    p.set_defaults(func=cmd_merge)

    p = sub.add_parser("clean", parents=[common],
                       help="delete traces older than N days")
    p.add_argument("--keep-days", type=int, default=30,
                   help="keep traces newer than this many days (default 30)")
    p.set_defaults(func=cmd_clean)

    p = sub.add_parser("stats", parents=[common],
                       help="one-glance store health numbers")
    p.add_argument("--by-agent", action="store_true",
                   help="per-agent rollup (steps, tokens, errors, "
                        "touched-trace failure rate) instead of totals")
    p.add_argument("--min-failed", type=int, metavar="N",
                   help="with --by-agent, keep only agents with at "
                        "least N failed traces (recidivist filter)")
    p.add_argument("--trend", action="store_true",
                   help="failure-rate history over time instead of totals")
    p.add_argument("--trend-bucket-days", type=int, default=7,
                   help="trend bucket size in days (default 7)")
    p.add_argument("--since", type=int, metavar="DAYS",
                   help="only traces created in the last DAYS days")
    p.add_argument("--json", action="store_true", help="emit JSON")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("cluster", parents=[common],
                       help="cross-trace failure clustering (recidivist modes)")
    p.add_argument("--min-size", type=int, default=2,
                   help="cluster size threshold for recidivists (default 2)")
    p.add_argument("--by-agent", action="store_true",
                   help="cluster recidivist AGENTS (failed-trace "
                        "participation) instead of modes")
    p.add_argument("--last", type=int,
                   help="only consider the N most recent traces")
    p.add_argument("--since", type=int, metavar="DAYS",
                   help="only traces created in the last DAYS days")
    p.add_argument("--json", action="store_true", help="emit JSON")
    p.set_defaults(func=cmd_cluster)

    p = sub.add_parser("curve", parents=[common],
                       help="token budget vs effective recall curve (HTML+SVG)")
    p.add_argument("trace")
    p.add_argument("-o", "--output", help="output HTML path")
    p.add_argument("--scatter", action="store_true",
                   help="overlay all store traces colored by success")
    p.add_argument("--budgets", help="comma-separated budget list, e.g. 200,500,1000")
    p.set_defaults(func=cmd_curve)

    p = sub.add_parser("distill", parents=[common],
                       help="export SFT training data for a local judge model")
    p.add_argument("-o", "--output", default="judge-sft.jsonl",
                   help="output JSONL path (default judge-sft.jsonl)")
    p.add_argument("--teacher", help="label with a strong judge model instead "
                                     "of the rule detectors")
    p.set_defaults(func=cmd_distill)

    p = sub.add_parser("export-dataset", parents=[common],
                       help="export labeled traces for benchmarking/sharing")
    p.add_argument("-o", "--output", default="dataset.jsonl",
                   help="output JSONL path (default dataset.jsonl)")
    p.add_argument("--teacher", help="label with a strong judge model instead "
                                     "of the rule detectors")
    p.set_defaults(func=cmd_export_dataset)

    p = sub.add_parser("benchmark", parents=[common],
                       help="evaluate attribution against a labeled dataset")
    p.add_argument("dataset", help="JSONL dataset path")
    p.add_argument("--format", choices=["approx", "mast"], default="approx",
                   help="dataset format (default approx)")
    p.add_argument("--judge", action="store_true", help="evaluate the LLM judge "
                                                        "instead of rules")
    p.add_argument("--judge-model", help="model for --judge")
    p.add_argument("--multi-label", action="store_true",
                   help="records carry a labels SET (from convert-mast "
                        "--multi-label); evaluate set-based P/R/F1")
    p.add_argument("--html", help="also write a self-contained HTML leaderboard "
                                  "to this path")
    p.set_defaults(func=cmd_benchmark)

    sub.add_parser("taxonomy", parents=[common],
                   help="print the MAST failure taxonomy").set_defaults(
        func=cmd_taxonomy
    )
    p_explain = sub.add_parser(
        "explain", parents=[common],
        help="deep dive on a MAST failure mode: definition, share, "
             "watching detectors, fixes")
    p_explain.add_argument("mode", nargs="?", default=None,
                           help="mode id (e.g. FM-1.3); omit for the "
                                "overview table")
    p_explain.set_defaults(func=cmd_explain)
    p_gate = sub.add_parser(
        "bench-gate", parents=[common],
        help="attribution-quality regression gate: dataset + floors -> "
             "exit 1 on any P/R/F1 breach")
    p_gate.add_argument("dataset", help="labeled JSONL dataset "
                                        "(approx format)")
    p_gate.add_argument("--floors", required=True,
                        help="floors JSON (sample_f1 + modes map)")
    p_gate.add_argument("--label", default="gate",
                        help="name shown in the log prefix")
    p_gate.set_defaults(func=cmd_bench_gate)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    # Windows consoles default to cp1252 and crash on box-drawing/arrow
    # glyphs; force UTF-8 with replacement so reporting never dies mid-run.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        try:
            if reconfigure is not None:
                reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):  # non-standard streams in tests
            pass
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "store", None) is None:
        args.store = None
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
