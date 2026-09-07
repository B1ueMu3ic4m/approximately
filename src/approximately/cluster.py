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
