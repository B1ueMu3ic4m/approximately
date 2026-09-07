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
    if args.open:
        import webbrowser

        webbrowser.open(path.as_uri())
    print("\nNext: point Recorder at your own agent — "
          "https://github.com/B1ueMu3ic4m/approximately#quickstart")
    return 0


def cmd_attribute(args: argparse.Namespace) -> int:
    store = TraceStore(args.store)
    trace = _load_trace(args.trace, store)
    report = attribute(trace, use_judge=args.judge)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        note = "" if report.judge_used or not args.judge else \
            "(judge requested but unavailable — rules only)"
        _print_report(report, note)
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    store = TraceStore(args.store)
    trace = _load_trace(args.trace, store)
    executor = _resolve_executor(args.executor)
    diff = replay(trace, executor)
    print(diff.summary())
    return 0 if diff.verdict != "diverged" else 1


def cmd_test(args: argparse.Namespace) -> int:
    store = TraceStore(args.store)
    trace = _load_trace(args.trace, store)
    report = attribute(trace)
    out = Path(args.output) if args.output else Path(f"test_approximately_{trace.id}.py")
    out.write_text(render_regression(trace, report), encoding="utf-8")
    print(f"wrote {out}")
    print("wire EXECUTOR (replay guard) and AGENT_ENTRY (contract guards), "
          "then run: pytest " + str(out))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    store = TraceStore(args.store)
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
        share = f" {mode.mast_share:5.2f}% of traces" if mode.mast_share else ""
        print(f"  {mode.id:<7} {mode.name}{share}")
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
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("attribute", parents=[common],
                       help="attribute a failure on a trace")
    p.add_argument("trace", help="trace id or path to trace JSON")
    p.add_argument("--judge", action="store_true",
                   help="add the LLM judge verdict (needs openai + API key)")
    p.add_argument("--json", action="store_true", help="emit JSON")
    p.set_defaults(func=cmd_attribute)

    p = sub.add_parser("replay", parents=[common],
                       help="replay a trace through an executor")
    p.add_argument("trace")
    p.add_argument("--executor", required=True,
                   help="executor as 'package.module:func' taking a Step")
    p.set_defaults(func=cmd_replay)

    p = sub.add_parser("test", parents=[common],
                       help="generate a pytest regression file")
    p.add_argument("trace")
    p.add_argument("-o", "--output", help="output test path")
    p.set_defaults(func=cmd_test)

    p = sub.add_parser("report", parents=[common],
                       help="render the HTML postmortem report")
    p.add_argument("trace")
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

    sub.add_parser("taxonomy", parents=[common],
                   help="print the MAST failure taxonomy").set_defaults(
        func=cmd_taxonomy
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    # Windows consoles default to cp1252 and crash on box-drawing/arrow
    # glyphs; force UTF-8 with replacement so reporting never dies mid-run.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):  # non-standard streams in tests
            pass
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "store", None) is None:
        args.store = None
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
