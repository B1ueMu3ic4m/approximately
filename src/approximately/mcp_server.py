"""Zero-dependency MCP (Model Context Protocol) stdio server.

Speaks JSON-RPC 2.0 over line-delimited stdio — the transport MCP
clients (Claude Desktop, Zed, IDEs) use — so an agent can call the
toolkit directly: list/query traces, attribute failures, verify
evidence, survey a fleet. Standard library only; no MCP SDK.

Protocol surface implemented: ``initialize``, ``notifications/
initialized``, ``ping``, ``tools/list``, ``tools/call``. Requests
longer than ``MAX_LINE`` bytes are rejected so a hostile client
cannot balloon memory; malformed JSON gets a -32700 error, unknown
methods -32601, bad params -32602.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import __version__

MAX_LINE = 1_000_000
PROTOCOL_VERSION = "2024-11-05"


SERVER_INFO = {"name": "approximately", "version": __version__}

_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "list_traces",
        "description": "List trace ids in a store with task, success "
                       "flag and step count.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "store": {"type": "string",
                          "description": "store directory (default: "
                                         "server's --store)"},
                "limit": {"type": "integer", "minimum": 1,
                          "maximum": 1000},
            },
        },
    },
    {
        "name": "attribute",
        "description": "Attribute a trace: primary MAST failure mode, "
                       "confidence, and per-detection evidence. With "
                       "explain=true the Bayesian fusion arithmetic "
                       "(prior log-odds + LLR per detection) rides "
                       "along, so the verdict is auditable.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "trace": {"type": "string"},
                "store": {"type": "string"},
                "explain": {"type": "boolean",
                            "description": "include the fusion "
                                           "arithmetic"},
            },
            "required": ["trace"],
        },
    },
    {
        "name": "verify",
        "description": "Verify the HMAC evidence chain of a trace. "
                       "Returns the full verdict payload: verdict "
                       "(intact, tampered, unsigned, keyed, wrong-key, "
                       "rolled-back, ledger-broken), detail, chain "
                       "finals, rollback flag and ledger health.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "trace": {"type": "string"},
                "store": {"type": "string"},
                "key_file": {"type": "string",
                             "description": "signing key file for "
                                            "HMAC-keyed traces"},
            },
            "required": ["trace"],
        },
    },
    {
        "name": "survey",
        "description": "Fleet summary over one or more store "
                       "directories: trace counts, failure rates, "
                       "trend verdicts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "stores": {"type": "array",
                           "items": {"type": "string"}},
            },
            "required": ["stores"],
        },
    },
    {
        "name": "bisect",
        "description": "First material divergence between two traces "
                       "(failed vs last success is the classic use): "
                       "the step where the failed run left the "
                       "successful run's path, with worst-ranked "
                       "divergences.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "trace": {"type": "string",
                          "description": "failed trace id"},
                "other": {"type": "string",
                          "description": "trace to compare against"},
                "store": {"type": "string"},
                "floor": {"type": "number",
                          "minimum": 0.0, "maximum": 1.01,
                          "description": "mutations with similarity "
                                         ">= floor count as noise "
                                         "(default 0.8)"},
            },
            "required": ["trace", "other"],
        },
    },
    {
        "name": "doctor",
        "description": "Health check of a trace store: corrupt or "
                       "misnamed records, evidence-ledger tamper, "
                       "stale locks, leftover temp files, and (with "
                       "digest_dir) monitoring gaps.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "store": {"type": "string"},
                "digest_dir": {"type": "string"},
            },
        },
    },
    {
        "name": "trend",
        "description": "Day-level analytics over a watch-loop digest "
                       "directory: per-day failure rate, sparkline, "
                       "Theil-Sen verdict. With an agent name, the "
                       "per-day rollup for that one agent instead "
                       "(visible while it stays among a store's "
                       "top-N busiest agents in the snapshots).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "digest_dir": {"type": "string",
                               "description": "directory of daily "
                                              "digest-*.jsonl files"},
                "agent": {"type": "string",
                          "description": "per-day analytics for one "
                                         "named agent (optional)"},
            },
            "required": ["digest_dir"],
        },
    },
    {
        "name": "scoreboard",
        "description": "Per-agent rollup for a store: steps, tool "
                       "calls, errors, tokens, failed traces, and "
                       "the touched-trace failure rate per agent "
                       "(steps without identity roll up under "
                       "unattributed). Optional query-expression "
                       "filter, e.g. \"success == false\". "
                       "min_failed keeps only repeat offenders.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "store": {"type": "string"},
                "expression": {"type": "string"},
                "top": {"type": "number",
                        "description": "keep the first N rows "
                                       "(default: all)"},
                "min_failed": {"type": "number",
                               "description": "keep only agents with "
                                              "at least N failed "
                                              "traces (default: all)"},
                "group_by": {"type": "string", "enum": ["agent", "tool"],
                             "description": "roll up per agent "
                                            "(default) or per tool"},
            },
        },
    },
    {
        "name": "cluster",
        "description": "Cross-trace failure clustering: attributes "
                       "every trace and groups failures by (mode, "
                       "tool-set); min_size keeps only recidivist "
                       "clusters. by_agent switches to recidivist "
                       "AGENTS instead of modes. Optional "
                       "query-expression filter.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "store": {"type": "string"},
                "expression": {"type": "string"},
                "min_size": {"type": "number",
                             "description": "cluster size threshold "
                                            "for recidivists "
                                            "(default 2)"},
                "by_agent": {"type": "boolean",
                             "description": "cluster recidivist "
                                            "agents instead of modes"},
                "top": {"type": "number",
                        "description": "keep the first N clusters "
                                       "(default: all)"},
            },
        },
    },
    {
        "name": "similar",
        "description": "Most alignment-similar traces to a given "
                       "trace, best first (structure-aware sequence "
                       "alignment over steps, score in [0, 1]).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "trace": {"type": "string"},
                "store": {"type": "string"},
                "top": {"type": "number",
                        "description": "how many candidates "
                                       "(default 5)"},
            },
            "required": ["trace"],
        },
    },
    {
        "name": "drift",
        "description": "Behaviour drift between the oldest and newest "
                       "traces of a store: Population Stability Index "
                       "over action histograms, with the biggest "
                       "shifted actions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "store": {"type": "string"},
                "baseline_ratio": {"type": "number",
                                   "description": "share of oldest "
                                                  "traces forming the "
                                                  "baseline window "
                                                  "(default 0.5)"},
            },
        },
    },
    {
        "name": "counterfactual",
        "description": "Leave-one-out attribution over every detected "
                       "step of a trace: which step's removal "
                       "eliminates each mode (root cause vs symptom), "
                       "distributed-cause verdict and causal ranking.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "trace": {"type": "string"},
                "store": {"type": "string"},
            },
            "required": ["trace"],
        },
    },
    {
        "name": "predict",
        "description": "Failure precursor score for a trace: mines "
                       "the store's other traces for action patterns "
                       "that precede failures, returns a failure "
                       "probability with contributors.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "trace": {"type": "string"},
                "store": {"type": "string"},
            },
            "required": ["trace"],
        },
    },
    {
        "name": "context",
        "description": "Context-runtime forecast for a trace: replay "
                       "the recorded run through a budgeted context "
                       "window (dry run) - what survives eviction, "
                       "fact recall, tokens saved.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "trace": {"type": "string"},
                "store": {"type": "string"},
                "budget": {"type": "number",
                           "description": "context-token budget "
                                          "(default 4000)"},
            },
            "required": ["trace"],
        },
    },
    {
        "name": "curve",
        "description": "Budget-recall sweep for a trace: recall of "
                       "ground-truth facts across a geometric grid of "
                       "context budgets (the what-if curve).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "trace": {"type": "string"},
                "store": {"type": "string"},
            },
            "required": ["trace"],
        },
    },
    {
        "name": "annotate",
        "description": "Attach an analyst note to a trace "
                       "(append-only sidecar; the evidence chain "
                       "stays untouched). With a note: writes it "
                       "(verdict: confirmed / false-positive are "
                       "the triage idioms). Without: returns the "
                       "annotations on file (trace filter "
                       "optional).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "store": {"type": "string"},
                "trace": {"type": "string"},
                "note": {"type": "string",
                         "description": "omit to read instead of "
                                        "write"},
                "author": {"type": "string"},
                "verdict": {"type": "string"},
            },
            "required": ["trace"],
        },
    },
    {
        "name": "anomalies",
        "description": "Latency anomaly detection for one trace: "
                       "per-step modified z-scores over tool-call "
                       "latency, worst first. isError is set when "
                       "anomalies exist.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "trace": {"type": "string"},
                "store": {"type": "string"},
                "threshold": {"type": "number",
                              "description": "z-score threshold "
                                             "(default 3.5)"},
            },
            "required": ["trace"],
        },
    },
    {
        "name": "diff",
        "description": "Structural diff of two traces (alignment "
                       "ops + similarity) with the divergences ranked "
                       "most-different first.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "store": {"type": "string"},
                "trace": {"type": "string"},
                "other": {"type": "string"},
            },
            "required": ["trace", "other"],
        },
    },
    {
        "name": "regression_test",
        "description": "Mint a self-contained pytest regression file "
                       "from a failed trace (the trace rides along as "
                       "base64): the failure can never silently "
                       "return. Returns the file content; write it "
                       "where your tests live.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "trace": {"type": "string"},
                "store": {"type": "string"},
                "budget": {"type": "number",
                           "description": "context-token budget "
                                          "guard (optional)"},
                "min_recall": {"type": "number",
                               "description": "fact-recall floor "
                                              "(default 0.8)"},
            },
            "required": ["trace"],
        },
    },
    {
        "name": "metrics",
        "description": "Store health as Prometheus text exposition: "
                       "trace count, failure rate, step/token means, "
                       "per-mode failure counts (and per-agent rates "
                       "with group_by agent).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "store": {"type": "string"},
                "group_by": {"type": "string",
                             "enum": ["store", "agent"],
                             "description": "store totals (default) "
                                            "or per-agent rates"},
            },
        },
    },
    {
        "name": "bench_gate",
        "description": "Attribution-quality regression gate: run the "
                       "rule detectors over a labeled JSONL dataset "
                       "and compare per-mode P/R/F1 plus sample "
                       "macro-F1 against a floors file. Reports "
                       "violations instead of exiting nonzero.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dataset": {"type": "string",
                            "description": "labeled JSONL dataset "
                                           "(approx format)"},
                "floors": {"type": "string",
                           "description": "floors JSON (sample_f1 + "
                                          "per-mode minimums)"},
            },
            "required": ["dataset", "floors"],
        },
    },
    {
        "name": "explain",
        "description": "Deep dive on a MAST failure mode: definition, "
                       "published share, the mechanical detectors that "
                       "watch for it, and engineering fixes. Omit the "
                       "mode for the overview table of all 14 modes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": {"type": "string",
                         "description": "mode id such as FM-1.3 "
                                        "(optional)"},
            },
        },
    },
    {
        "name": "stats",
        "description": "Aggregate a query selection instead of "
                       "listing it: count, success split, failure "
                       "rate, mode totals, mean steps/tokens.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "expression": {"type": "string"},
                "store": {"type": "string"},
            },
            "required": ["expression"],
        },
    },
    {
        "name": "query",
        "description": "Select traces with an expression, e.g. "
                       "\"success == false and mode == FM-2.1\".",
        "inputSchema": {
            "type": "object",
            "properties": {
                "expression": {"type": "string"},
                "store": {"type": "string"},
            },
            "required": ["expression"],
        },
    },
]


class ServerContext:
    """Default store binding shared by the tools."""

    def __init__(self, store: str):
        self.store = store


def _store(ctx: ServerContext, args: Dict[str, Any]):
    from .store import TraceStore

    return TraceStore(Path(args.get("store") or ctx.store))


def _tool_list_traces(ctx: ServerContext, args: Dict[str, Any]) -> dict:
    limit = int(args.get("limit", 100))
    traces = _store(ctx, args).list_traces()[:limit]
    return {"traces": [{"id": t.id, "task": t.task,
                        "success": t.success,
                        "steps": len(t.steps)} for t in traces]}


def _tool_attribute(ctx: ServerContext, args: Dict[str, Any]) -> dict:
    from .attributor import attribute

    store = _store(ctx, args)
    trace = store.load(str(args["trace"]))
    if trace is None:
        raise KeyError(f"no trace {args['trace']!r} in store")
    report = attribute(trace)
    payload = {
        "trace": trace.id,
        "failed": report.failed,
        "primary_mode": report.primary_mode.id,
        "runner_ups": report.runner_ups,
        "label": report.category_label,
        "detections": [{"mode": d.mode_id,
                        "step": d.step_index,
                        "confidence": d.confidence,
                        "source": d.source,
                        "evidence": d.evidence}
                       for d in report.detections],
    }
    if args.get("explain"):
        from .attributor import explain_fusion

        payload["fusion_explanation"] = explain_fusion(
            report.detections)
    return payload


def _tool_verify(ctx: ServerContext, args: Dict[str, Any]) -> dict:
    from .integrity import load_key, verdict_payload

    store = _store(ctx, args)
    trace = store.load(str(args["trace"]))
    if trace is None:
        raise KeyError(f"no trace {args['trace']!r} in store")
    key = (load_key(str(args["key_file"]))
           if args.get("key_file") else None)
    return {"trace": trace.id,
            **verdict_payload(trace, store.directory, key=key)}


def _tool_survey(ctx: ServerContext, args: Dict[str, Any]) -> dict:
    from .fleet import survey, webhook_payload

    paths = [Path(p) for p in args["stores"]]
    return webhook_payload(survey(paths))


def _tool_query(ctx: ServerContext, args: Dict[str, Any]) -> dict:
    from .query import select

    found = select(_store(ctx, args).list_traces(),
                   str(args["expression"]))
    return {"count": len(found),
            "ids": [t.id for t in found]}


def _tool_bisect(ctx: ServerContext, args: Dict[str, Any]) -> dict:
    from .diff import diff as trace_diff
    from .diff import first_fault

    store = _store(ctx, args)
    trace_a = store.load(str(args["trace"]))
    trace_b = store.load(str(args["other"]))
    if trace_a is None:
        raise KeyError(f"no trace {args['trace']!r} in store")
    if trace_b is None:
        raise KeyError(f"no trace {args['other']!r} in store")
    td = trace_diff(trace_a, trace_b)
    fault = first_fault(td, floor=float(args.get("floor", 0.8)))
    return {
        "a_id": td.a_id, "b_id": td.b_id,
        "similarity": round(td.similarity, 3),
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
                        for e in td.divergences(limit=5)],
    }


def _tool_doctor(ctx: ServerContext, args: Dict[str, Any]) -> dict:
    from .doctor import doctor

    digest_dir = args.get("digest_dir")
    report = doctor(_store(ctx, args).directory,
                    Path(digest_dir) if digest_dir else None)
    return report.to_dict()


def _tool_trend(ctx: ServerContext, args: Dict[str, Any]) -> dict:
    from .fleet import agent_trend_days, summarize_agent_trend, summarize_trend, trend_days

    days = trend_days(Path(str(args["digest_dir"])))
    agent = args.get("agent")
    if agent:
        agent_days = agent_trend_days(Path(str(args["digest_dir"])),
                                      str(agent))
        summary = summarize_agent_trend(agent_days)
        return {"agent": str(agent), **summary}
    return summarize_trend(days)


def _tool_stats(ctx: ServerContext, args: Dict[str, Any]) -> dict:
    from .query import select, summarize

    found = select(_store(ctx, args).list_traces(),
                   str(args["expression"]))
    return summarize(found)


def _tool_scoreboard(ctx: ServerContext, args: Dict[str, Any]) -> dict:
    traces = _store(ctx, args).list_traces()
    if args.get("expression"):
        from .query import select

        traces = select(traces, str(args["expression"]))
    if str(args.get("group_by") or "agent") == "tool":
        from .cluster import tool_scorecard

        rows = tool_scorecard(traces)
    else:
        from .cluster import agent_scorecard

        min_failed = args.get("min_failed")
        rows = agent_scorecard(
            traces,
            min_failed=(int(min_failed)
                        if min_failed is not None else None),
        )
    top = args.get("top")
    if top is not None:
        rows = rows[:max(0, int(top))]
    return {"agents": rows, "traces_scanned": len(traces)}


def _tool_bench_gate(ctx: ServerContext, args: Dict[str, Any]) -> dict:
    from .benchgate import gate_result

    for key in ("dataset", "floors"):
        if not args.get(key):
            raise KeyError(f"bench_gate requires {key!r}")
    return gate_result(Path(str(args["dataset"])),
                       Path(str(args["floors"])))


def _tool_cluster(ctx: ServerContext, args: Dict[str, Any]) -> dict:
    traces = _store(ctx, args).list_traces()
    if args.get("expression"):
        from .query import select

        traces = select(traces, str(args["expression"]))
    min_size = int(args["min_size"]) if args.get("min_size") else 2
    if args.get("by_agent"):
        from .cluster import agent_scorecard

        rows = [r for r in agent_scorecard(traces)
                if r["failed_traces"] >= min_size]
        return {"recidivist_agents": rows,
                "traces_scanned": len(traces)}
    from .cluster import cluster

    report = cluster(traces)
    clusters = [{"mode_id": c.mode_id, "size": c.size,
                 "tools": list(c.tools),
                 "example_task": c.example_task}
                for c in report.clusters if c.size >= min_size]
    top = args.get("top")
    if top is not None:
        clusters = clusters[:max(0, int(top))]
    return {"traces_scanned": report.traces_scanned,
            "failures_found": report.failures_found,
            "clusters": clusters}


def _tool_similar(ctx: ServerContext, args: Dict[str, Any]) -> dict:
    from .align import similar_payload

    store = _store(ctx, args)
    trace = store.load(str(args["trace"]))
    if trace is None:
        raise KeyError(f"no trace {args['trace']!r} in store")
    top = int(args["top"]) if args.get("top") else 5
    return similar_payload(trace, store.list_traces(), top=top)


def _tool_drift(ctx: ServerContext, args: Dict[str, Any]) -> dict:
    from .drift import detect_drift

    traces = sorted(_store(ctx, args).list_traces(),
                    key=lambda t: t.created_at)
    ratio = float(args.get("baseline_ratio", 0.5) or 0.5)
    split_at = int(len(traces) * ratio)
    baseline, current = traces[:split_at], traces[split_at:]
    if not baseline or not current:
        raise KeyError("need traces in both windows (baseline = "
                       "oldest, current = newest)")
    from .drift import report_payload

    report = detect_drift(baseline, current)
    return report_payload(report)


def _tool_counterfactual(ctx: ServerContext, args: Dict[str, Any]) -> dict:
    from .counterfactual import counterfactual, report_payload

    store = _store(ctx, args)
    trace = store.load(str(args["trace"]))
    if trace is None:
        raise KeyError(f"no trace {args['trace']!r} in store")
    return report_payload(counterfactual(trace))


def _tool_predict(ctx: ServerContext, args: Dict[str, Any]) -> dict:
    from .precursor import PrecursorModel

    store = _store(ctx, args)
    trace = store.load(str(args["trace"]))
    if trace is None:
        raise KeyError(f"no trace {args['trace']!r} in store")
    model = PrecursorModel()
    for t in store.list_traces():
        if t.id != trace.id:
            model.observe(t)
    from .precursor import score_payload

    score = model.probability(trace)
    return score_payload(trace, score)


def _tool_context(ctx: ServerContext, args: Dict[str, Any]) -> dict:
    from .context import default_facts, forecast, forecast_payload

    store = _store(ctx, args)
    trace = store.load(str(args["trace"]))
    if trace is None:
        raise KeyError(f"no trace {args['trace']!r} in store")
    budget = int(args["budget"]) if args.get("budget") else 4000
    fc = forecast(trace, budget=max(1, budget),
                  facts=default_facts(trace))
    return forecast_payload(fc)


def _tool_curve(ctx: ServerContext, args: Dict[str, Any]) -> dict:
    from .curve import budget_curve, curve_payload

    store = _store(ctx, args)
    trace = store.load(str(args["trace"]))
    if trace is None:
        raise KeyError(f"no trace {args['trace']!r} in store")
    return curve_payload(budget_curve(trace))


def _tool_metrics(ctx: ServerContext, args: Dict[str, Any]) -> dict:
    from .cluster import agent_scorecard, store_stats
    from .metrics import render_agent_prometheus, render_prometheus

    store = _store(ctx, args)
    traces = store.list_traces()
    stats = store_stats(traces)
    if str(args.get("group_by") or "store") == "agent":
        rows = agent_scorecard(traces)
        text = render_agent_prometheus(rows)
    else:
        text = render_prometheus(stats)
    return {"store": str(store.directory),
            "content_type": "text/plain; version=0.0.4",
            "metrics": text}


def _tool_regression_test(ctx: ServerContext,
                          args: Dict[str, Any]) -> dict:
    from .attributor import attribute
    from .regress import render_regression

    store = _store(ctx, args)
    trace = store.load(str(args["trace"]))
    if trace is None:
        raise KeyError(f"no trace {args['trace']!r} in store")
    report = attribute(trace)
    budget = int(args["budget"]) if args.get("budget") else None
    min_recall = (float(args["min_recall"])
                  if args.get("min_recall") else 0.8)
    content = render_regression(trace, report, budget=budget,
                                min_recall=min_recall)
    return {"trace": trace.id,
            "filename": f"test_approximately_{trace.id}.py",
            "bytes": len(content),
            "content": content}


def _tool_anomalies(ctx: ServerContext, args: Dict[str, Any]) -> dict:
    from .anomaly import MODIFIED_Z_THRESHOLD, detect_latency_anomalies, summarize_anomalies

    store = _store(ctx, args)
    trace = store.load(str(args["trace"]))
    if trace is None:
        raise KeyError(f"no trace {args['trace']!r} in store")
    threshold = (float(args["threshold"])
                 if args.get("threshold")
                 else MODIFIED_Z_THRESHOLD)
    anomalies = detect_latency_anomalies(trace, threshold=threshold)
    return {"trace": trace.id,
            "count": len(anomalies),
            "summary": summarize_anomalies(anomalies),
            "anomalies": [{"step": a.step_index,
                           "tool": a.tool,
                           "latency_ms": a.latency_ms,
                           "z": round(a.robust_z, 3),
                           "median_ms": a.median_ms}
                          for a in anomalies]}


def _tool_diff(ctx: ServerContext, args: Dict[str, Any]) -> dict:
    from .diff import diff as trace_diff

    store = _store(ctx, args)
    a = store.load(str(args["trace"]))
    if a is None:
        raise KeyError(f"no trace {args['trace']!r} in store")
    b = store.load(str(args["other"]))
    if b is None:
        raise KeyError(f"no trace {args['other']!r} in store")
    td = trace_diff(a, b)
    return {"a": td.a_id, "b": td.b_id,
            "similarity": round(td.similarity, 4),
            "counts": {op.name.lower(): n
                       for op, n in td.counts.items() if n},
            "divergences": [{"op": e.op.name.lower(),
                             "a_index": e.a_index, "b_index": e.b_index,
                             "similarity": round(e.similarity, 4),
                             "detail": e.detail}
                            for e in td.divergences(limit=5)]}


def _tool_annotate(ctx: ServerContext, args: Dict[str, Any]) -> dict:
    store = _store(ctx, args)
    trace_id = str(args["trace"])
    if not args.get("note"):
        rows = store.annotations(trace_id)
        return {"trace": trace_id, "annotations": rows}
    entry = store.annotate(trace_id, str(args["note"]),
                           author=str(args.get("author", "") or ""),
                           verdict=str(args.get("verdict", "") or ""))
    return {"trace": trace_id, "annotated": True,
            "total_on_file": len(store.annotations(trace_id)),
            "entry": entry}


def _tool_explain(ctx: ServerContext, args: Dict[str, Any]) -> dict:
    from .explain import explain_overview, explain_text
    from .taxonomy import FAILURE_MODES

    mode = args.get("mode")
    if not mode:
        return {"overview": explain_overview()}
    if str(mode) not in FAILURE_MODES:
        raise KeyError(f"unknown failure mode {mode!r}")
    return {"mode": str(mode), "text": explain_text(str(mode))}


_HANDLERS = {
    "list_traces": _tool_list_traces,
    "attribute": _tool_attribute,
    "verify": _tool_verify,
    "survey": _tool_survey,
    "query": _tool_query,
    "bisect": _tool_bisect,
    "doctor": _tool_doctor,
    "trend": _tool_trend,
    "stats": _tool_stats,
    "explain": _tool_explain,
    "bench_gate": _tool_bench_gate,
    "scoreboard": _tool_scoreboard,
    "cluster": _tool_cluster,
    "similar": _tool_similar,
    "drift": _tool_drift,
    "counterfactual": _tool_counterfactual,
    "predict": _tool_predict,
    "context": _tool_context,
    "curve": _tool_curve,
    "annotate": _tool_annotate,
    "anomalies": _tool_anomalies,
    "diff": _tool_diff,
    "regression_test": _tool_regression_test,
    "metrics": _tool_metrics,
}


def _error(request_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id,
            "error": {"code": code, "message": message}}


def _resources(ctx: ServerContext) -> List[dict]:
    """Store contents as MCP resources: one entry per trace plus the
    annotation sidecar, so clients can browse a store without
    calling tools."""
    store = _store(ctx, {})
    out = [{
        "uri": f"approximately://{store.directory}/annotations.jsonl",
        "name": "annotations",
        "mimeType": "application/x-ndjson",
    }]
    out.extend({
        "uri": f"approximately://{store.directory}/traces/{trace.id}",
        "name": trace.task[:60] or trace.id,
        "mimeType": "application/json",
        "description": f"{len(trace.steps)} steps, "
                       f"{'failed' if trace.success is False else 'ok'}",
    } for trace in store.list_traces())
    return out


def _resources_read(msg: Dict[str, Any], ctx: ServerContext,
                    request_id) -> dict:
    uri = str(((msg.get("params") or {}).get("uri")) or "")
    if not uri.startswith("approximately://"):
        return _error(request_id, -32602,
                      f"unsupported uri scheme: {uri[:40]!r}")
    rest = uri[len("approximately://"):]
    store = _store(ctx, {})
    prefix = f"{store.directory}/traces/"
    if rest == f"{store.directory}/annotations.jsonl":
        import json as _json

        rows = store.annotations()
        body = "".join(_json.dumps(r, ensure_ascii=False) + "\n"
                       for r in rows)
        text = body
        mime = "application/x-ndjson"
    elif rest.startswith(prefix):
        trace_id = rest[len(prefix):]
        trace = store.load(trace_id)
        if trace is None:
            return _error(request_id, -32602,
                          f"no trace {trace_id!r} in store")
        text = trace.to_json()
        mime = "application/json"
    else:
        return _error(request_id, -32602, f"unknown resource {uri[:60]!r}")
    return {"jsonrpc": "2.0", "id": request_id,
            "result": {"contents": [{"uri": uri, "mimeType": mime,
                                     "text": text}]}}


def handle_request(msg: Dict[str, Any], ctx: ServerContext) -> Optional[dict]:
    """One JSON-RPC request -> response dict, or None for
    notifications. Raises ValueError for malformed envelopes."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        raise ValueError("not a JSON-RPC 2.0 message")
    method = str(msg.get("method"))
    request_id = msg.get("id")
    if request_id is None:
        return None  # notification: accepted, never answered
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": request_id,
                "result": {"protocolVersion": PROTOCOL_VERSION,
                           "capabilities": {"tools": {},
                                            "resources": {}},
                           "serverInfo": SERVER_INFO}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "resources/list":
        return {"jsonrpc": "2.0", "id": request_id,
                "result": {"resources": _resources(ctx)}}
    if method == "resources/read":
        return _resources_read(msg, ctx, request_id)
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id,
                "result": {"tools": _TOOLS}}
    if method == "tools/call":
        return _tools_call(msg, ctx, request_id)
    return _error(request_id, -32601, f"unknown method {method!r}")


def _tools_call(msg: Dict[str, Any], ctx: ServerContext,
                request_id) -> dict:
    params: Dict[str, Any] = msg.get("params") or {}
    name = str(params.get("name") or "")
    handler = _HANDLERS.get(name)
    if handler is None:
        return _error(request_id, -32602, f"unknown tool {name!r}")
    tool_args = params.get("arguments") or {}
    try:
        payload = handler(ctx, tool_args)
    except KeyError as exc:
        payload = {"error": str(exc)}
    except Exception as exc:  # tool-level failure, still a result
        payload = {"error": f"{type(exc).__name__}: {exc}"}
    return {"jsonrpc": "2.0", "id": request_id,
            "result": {"content": [
                {"type": "text", "text": json.dumps(payload, indent=2,
                                                    default=str)}],
                "isError": "error" in payload}}


def serve(read, write, ctx: ServerContext,
          max_requests: Optional[int] = None) -> int:
    """Line-delimited loop over two byte/text streams. Returns the
    number of responses written. Malformed JSON lines produce a
    -32700 error but do not stop the server."""
    handled = 0
    while max_requests is None or handled < max_requests:
        try:
            line = read()
        except StopIteration:  # iterator-backed streams: clean EOF
            break
        if line is None or line == "":
            break
        response = _handle_line(line.strip(), ctx)
        if response is not None:
            write(json.dumps(response) + "\n")
            handled += 1
    return handled


def _handle_line(line: str, ctx: ServerContext) -> Optional[dict]:
    """One input line -> one response (None for notifications)."""
    if not line:
        return None
    if len(line) > MAX_LINE:
        return _error(None, -32600, "request too large")
    try:
        msg: Any = json.loads(line)
    except json.JSONDecodeError:
        return _error(None, -32700, "parse error")
    if not isinstance(msg, dict):
        return _error(None, -32600, "invalid request envelope")
    try:
        return handle_request(msg, ctx)
    except ValueError:
        return _error(msg.get("id"), -32600, "invalid request envelope")


def cmd_mcp(args) -> int:
    """CLI entry: serve MCP over real stdio."""
    ctx = ServerContext(args.store)
    stdin = getattr(args, "_stdin", sys.stdin)
    stdout = getattr(args, "_stdout", sys.stdout)
    served = serve(stdin.readline, stdout.write, ctx,
                   max_requests=getattr(args, "_max_requests", None))
    stdout.flush()
    if getattr(args, "_report", False):
        print(f"served {served} request(s)", file=sys.stderr)
    return 0
