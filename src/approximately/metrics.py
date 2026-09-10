"""Prometheus exposition format export for store statistics.

Ops-grade integration: `approximately metrics --prometheus` emits text
that a Prometheus scraper can consume directly (or expose via
pushgateway). Agent reliability joins the same dashboards and alerts as
every other service:

    approximately_runs_total / failures_total / failure_rate
    approximately_mode_count{mode="FM-1.3"}
    approximately_steps_average

Label values are escaped per the Prometheus text-exformat rules
(backslash, double quote, newline) — task strings are untrusted input.
"""

from __future__ import annotations


def escape_label(value: str) -> str:
    """Escape a label value per Prometheus text-exposition rules."""
    return (value.replace("\\", "\\\\")
                 .replace('"', '\\"')
                 .replace("\n", "\\n"))


def render_prometheus(stats, extra_labels: dict | None = None) -> str:
    """Render store statistics as Prometheus text exposition format."""
    labels = ""
    if extra_labels:
        pairs = ",".join(
            f'{k}="{escape_label(str(v))}"' for k, v in extra_labels.items()
        )
        labels = "{" + pairs + "}"
    lines = [
        "# HELP approximately_runs_total Total recorded agent runs",
        "# TYPE approximately_runs_total counter",
        f"approximately_runs_total{labels} {stats.traces}",
        "# HELP approximately_failures_total Runs attributed as failed",
        "# TYPE approximately_failures_total counter",
        f"approximately_failures_total{labels} {stats.failures}",
        "# HELP approximately_failure_rate Fraction of failed runs",
        "# TYPE approximately_failure_rate gauge",
        (f"approximately_failure_rate{labels} "
         f"{stats.failure_rate:.6f}"),
        "# HELP approximately_steps_average Average steps per run",
        "# TYPE approximately_steps_average gauge",
        (f"approximately_steps_average{labels} "
         f"{stats.avg_steps:.4f}"),
    ]
    for mode_id, count in sorted(stats.mode_counts.items()):
        safe = escape_label(mode_id)
        extra = "," + labels if labels else ""
        lines.extend([
            "# HELP approximately_mode_count Failures per MAST mode",
            "# TYPE approximately_mode_count counter",
            f'approximately_mode_count{{mode="{safe}"{extra}}} {count}',
        ])
    lines.append("")
    return "\n".join(lines)
