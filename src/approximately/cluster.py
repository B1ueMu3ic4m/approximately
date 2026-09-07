"""Cross-trace failure clustering: find your team's recidivist modes.

One trace tells you why a run failed. A hundred traces tell you what your
agent *systematically* gets wrong — the recidivist failure modes worth an
afternoon of engineering (MAST: specification & design issues account for
41.8% of failures; they are structural, so they repeat).

Clustering rule: two failed traces share a cluster when they were attributed
to the same MAST mode and their failing steps touch the same tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

from .attributor import attribute
from .detectors import args_hash
from .taxonomy import OTHER
from .trace import TOOL_CALL, Trace


@dataclass
class Cluster:
    mode_id: str
    tools: Tuple[str, ...]          # sorted tool names in the failing steps
    traces: List[Trace] = field(default_factory=list)
    example_task: str = ""
    signature_args: List[str] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.traces)

    def summary(self) -> str:
        return (f"{self.mode_id} x{self.size} via {','.join(self.tools) or '-'}"
                f"  e.g. {self.example_task[:60]}")


@dataclass
class ClusterReport:
    clusters: List[Cluster] = field(default_factory=list)
    traces_scanned: int = 0
    failures_found: int = 0

    def recidivists(self, min_size: int = 2) -> List[Cluster]:
        return [c for c in self.clusters if c.size >= min_size]

    def summary(self, min_size: int = 2) -> str:
        lines = [
            f"scanned {self.traces_scanned} traces, "
            f"{self.failures_found} failures, "
            f"{len(self.clusters)} clusters"
        ]
        recidivists = self.recidivists(min_size)
        if recidivists:
            lines.append(f"recidivist clusters (size >= {min_size}):")
            for cluster in recidivists:
                lines.append(f"  - {cluster.summary()}")
        else:
            lines.append(f"no cluster reaches size {min_size}")
        return "\n".join(lines)


def _cluster_key(trace: Trace, mode_id: str) -> Tuple[str, Tuple[str, ...]]:
    tools = tuple(sorted({s.tool for s in trace.steps
                          if s.kind == TOOL_CALL and s.tool}))
    return mode_id, tools


def cluster(traces: Iterable[Trace], use_judge: bool = False) -> ClusterReport:
    """Attribute every trace and group failures by (mode, tool-set)."""
    report = ClusterReport()
    by_key: Dict[Tuple[str, Tuple[str, ...]], Cluster] = {}

    for trace in traces:
        report.traces_scanned += 1
        failure_report = attribute(trace, use_judge=use_judge)
        if not failure_report.failed or failure_report.primary_mode.id == OTHER:
            continue
        report.failures_found += 1
        mode_id = failure_report.primary_mode.id
        key = _cluster_key(trace, mode_id)
        cluster = by_key.get(key)
        if cluster is None:
            cluster = Cluster(mode_id=mode_id, tools=key[1])
            by_key[key] = cluster
        cluster.traces.append(trace)
        if not cluster.example_task:
            cluster.example_task = trace.task
        # remember repeated argument signatures inside the cluster
        for det in failure_report.detections:
            if det.mode_id == "FM-1.3":
                step = trace.steps[det.step_index]
                cluster.signature_args.append(args_hash(step.args))

    report.clusters = sorted(by_key.values(), key=lambda c: -c.size)
    return report


@dataclass
class StoreStats:
    traces: int = 0
    failures: int = 0
    mode_counts: Dict[str, int] = field(default_factory=dict)
    avg_steps: float = 0.0

    @property
    def failure_rate(self) -> float:
        return self.failures / self.traces if self.traces else 0.0

    def summary(self) -> str:
        lines = [
            f"{self.traces} traces · {self.failures} failures "
            f"(failure rate {self.failure_rate:.0%}) · "
            f"avg {self.avg_steps:.1f} steps"
        ]
        if self.mode_counts:
            lines.append("top failure modes:")
            for mode_id, count in sorted(self.mode_counts.items(),
                                         key=lambda kv: -kv[1])[:5]:
                lines.append(f"  {mode_id:<7} x{count}")
        return "\n".join(lines)


def store_stats(traces: Iterable[Trace]) -> StoreStats:
    """One-glance health numbers for a store (single attribution pass)."""
    stats = StoreStats()
    total_steps = 0
    for trace in traces:
        stats.traces += 1
        total_steps += len(trace.steps)
        if trace.success is False:
            stats.failures += 1
            report = attribute(trace)
            if report.primary_mode.id != OTHER:
                stats.mode_counts[report.primary_mode.id] = (
                    stats.mode_counts.get(report.primary_mode.id, 0) + 1
                )
    stats.avg_steps = total_steps / stats.traces if stats.traces else 0.0
    return stats


def trend(traces: Iterable[Trace], bucket_days: int = 7) -> List[dict]:
    """Failure-rate history over time, oldest bucket first.

    Buckets traces by creation date and reports the failure rate per
    bucket — the "is the agent getting better or worse?" line.
    """
    rows = list(traces)
    if not rows:
        return []
    import datetime

    times = [t.created_at or 0 for t in rows]
    start = min(times)
    buckets: Dict[int, Dict[str, int]] = {}
    for trace in rows:
        age = ((trace.created_at or 0) - start) / 86400
        bucket = int(age // bucket_days)
        b = buckets.setdefault(bucket, {"total": 0, "failed": 0})
        b["total"] += 1
        if trace.success is False:
            b["failed"] += 1
    start_date = datetime.datetime.fromtimestamp(
        start or 0, datetime.timezone.utc
    )
    out = []
    for bucket in sorted(buckets):
        b = buckets[bucket]
        out.append({
            "bucket_start": (start_date
                             + datetime.timedelta(days=bucket * bucket_days)
                             ).strftime("%Y-%m-%d"),
            "total": b["total"],
            "failed": b["failed"],
            "failure_rate": round(b["failed"] / b["total"], 3),
        })
    return out
