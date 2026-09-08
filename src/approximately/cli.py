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


def _print_report(report, judge_note: str = "") -> None:
    bar = "─" * 62
    print(bar)
    print(f"  VERDICT  {report.primary_mode.label}")
    if judge_note:
        print(f"  {judge_note}")
    print(f"  {report.summary}")
    print(bar)
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
    else:
        trace, report, path = run_demo()
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
    if args.patched:
        patched = _resolve_executor(args.patched)
        diff_b = replay(trace, patched, threshold=args.threshold)
        print(compare(diff, diff_b))
        print("--- original:")
        print(diff.summary())
        print("--- patched:")
        print(diff_b.summary())
        return 0
    print(diff.summary())
    return 0 if diff.verdict != "diverged" else 1


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
    from .report import render_index_html

    store = TraceStore(args.store)
    if args.all:
        pairs = []
        written = 0
        for trace in store.list_traces():
            report = attribute(trace, use_judge=args.judge)
            pairs.append((trace, report))
            # write every individual report so the index links resolve
            page = store.directory / f"{trace.id}.report.html"
            if not page.exists():
                page.write_text(render_html(trace, report), encoding="utf-8")
                written += 1
        out = Path(args.output) if args.output else store.directory / "index.html"
        out.write_text(render_index_html(pairs), encoding="utf-8")
        print(f"wrote index over {len(pairs)} traces: {out} "
              f"({written} individual reports generated)")
        return 0
    trace = _load_trace(args.trace, store)
    report = attribute(trace, use_judge=args.judge)
    out = Path(args.output) if args.output else store.directory / f"{trace.id}.report.html"
    out.write_text(render_html(trace, report), encoding="utf-8")
    print(f"wrote {out}")
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


def cmd_verify(args: argparse.Namespace) -> int:
    from .integrity import load_key, verify

    store = TraceStore(args.store)
    trace = _load_trace(args.trace, store)
    key = load_key(args.key_file)
    result = verify(trace, key=key)
    if result.verdict == "unsigned":
        print("unsigned: trace carries no integrity block "
              "(recorded before v0.3.1)")
        return 2
    if result.verdict == "keyed":
        print(f"KEYED: {result.detail}")
        return 3
    if result.intact:
        kind = "HMAC-authenticated" if key else "intact"
        print(f"{kind}: {result.detail}")
        print(f"  chain final: {result.actual_final}")
        return 0
    print(f"TAMPERED: {result.detail}")
    print(f"  expected chain final: {result.expected_final}")
    print(f"  actual chain final:   {result.actual_final}")
    return 1


def cmd_clean(args: argparse.Namespace) -> int:
    store = TraceStore(args.store)
    removed = store.clean(keep_days=args.keep_days)
    print(f"removed {removed} traces older than {args.keep_days} days")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    from .cluster import store_stats

    store = TraceStore(args.store)
    traces = store.list_traces()
    stats = store_stats(traces)
    if args.trend:
        from .cluster import trend

        buckets = trend(store.list_traces(),
                        bucket_days=args.trend_bucket_days)
        if args.json:
            print(json.dumps(buckets, indent=2))
            return 0
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
    store = TraceStore(args.store)
    if args.all:
        results = []
        for trace in store.list_traces():
            report = attribute(trace, use_judge=args.judge)
            entry = report.to_dict()
            entry["trace"] = {"id": trace.id, "task": trace.task,
                              "success": trace.success,
                              "steps": len(trace.steps)}
            results.append(entry)
        print(json.dumps(results, indent=2))
        return 0
    trace = _load_trace(args.trace, store)
    report = attribute(trace, use_judge=args.judge)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        note = "" if report.judge_used or not args.judge else \
            "(judge requested but unavailable — rules only)"
        _print_report(report, note)
    return 0


def cmd_cluster(args: argparse.Namespace) -> int:
    from .cluster import cluster

    store = TraceStore(args.store)
    traces = store.list_traces()
    if args.last:
        traces = traces[-args.last:]
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


def cmd_benchmark(args: argparse.Namespace) -> int:
    from .distill import evaluate, load_dataset, rules_labeler, teacher_labeler

    labeled = load_dataset(Path(args.dataset), fmt=args.format)
    if not labeled:
        print("no labeled records found")
        return 1
    if args.judge:
        labeler = teacher_labeler(args.judge_model or "gpt-4o-mini")
        source = f"judge {args.judge_model or 'gpt-4o-mini'}"
    else:
        labeler = rules_labeler()
        source = "rule detectors"
    result = evaluate(labeled, labeler)
    print(f"labeled {len(labeled)} traces · predictor: {source}")
    print(result.summary())
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

    # --store is accepted both before and after the subcommand
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--store", help=argparse.SUPPRESS)

    p = sub.add_parser("demo", parents=[common],
                       help="run the built-in failing agent (30s tour)")
    p.add_argument("--open", action="store_true", help="open the HTML report")
    p.add_argument("--context-budget", type=int, default=60,
                   help="token budget for the context-runtime demo (default 60)")
    p.add_argument("--scenario", choices=["booking", "multi-agent"],
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
    p.add_argument("--all", action="store_true",
                   help="attribute every trace in the store (JSON output)")
    p.set_defaults(func=cmd_attribute)

    p = sub.add_parser("replay", parents=[common],
                       help="replay a trace through an executor")
    p.add_argument("trace")
    p.add_argument("--executor", required=True,
                   help="executor as 'package.module:func' taking a Step")
    p.add_argument("--patched",
                   help="A/B: a second executor to compare against --executor")
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
    p.add_argument("--judge", action="store_true")
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

    p = sub.add_parser("verify", parents=[common],
                       help="verify the tamper-evident hash chain of a trace")
    p.add_argument("trace")
    p.add_argument("--key-file",
                   help="signing key file for HMAC-keyed traces")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("clean", parents=[common],
                       help="delete traces older than N days")
    p.add_argument("--keep-days", type=int, default=30,
                   help="keep traces newer than this many days (default 30)")
    p.set_defaults(func=cmd_clean)

    p = sub.add_parser("stats", parents=[common],
                       help="one-glance store health numbers")
    p.add_argument("--trend", action="store_true",
                   help="failure-rate history over time instead of totals")
    p.add_argument("--trend-bucket-days", type=int, default=7,
                   help="trend bucket size in days (default 7)")
    p.add_argument("--json", action="store_true", help="emit JSON")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("cluster", parents=[common],
                       help="cross-trace failure clustering (recidivist modes)")
    p.add_argument("--min-size", type=int, default=2,
                   help="cluster size threshold for recidivists (default 2)")
    p.add_argument("--last", type=int,
                   help="only consider the N most recent traces")
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
    p.set_defaults(func=cmd_benchmark)

    sub.add_parser("taxonomy", parents=[common],
                   help="print the MAST failure taxonomy").set_defaults(
        func=cmd_taxonomy
    )
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
