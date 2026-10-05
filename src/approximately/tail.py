"""The tail: one line per arrival, a scream per failure.

``fleet --watch`` watches digest metrics; this watches *arrivals*.
A long-running agent fleet writes traces continuously, and the
operator's question is "what just landed?" — printed the moment it
lands, with failed runs flagged and (optionally) announced through
the same HMAC-signed webhook channel the fleet uses. ``--once``
makes a single pass and exits: the cron-able shape of the same door.
"""

from __future__ import annotations

import time
from typing import Any, List, Optional, Set

from .trace import Trace


def scan_pass(store: Any, seen: Set[str]) -> List[Trace]:
    """Traces that arrived since the last pass, oldest first. A
    trace unreadable on arrival is skipped loudly by the store and
    retried next pass — a half-written file is not a missing one."""
    arrivals = []
    for trace in store.list_traces():
        if trace.id not in seen:
            seen.add(trace.id)
            arrivals.append(trace)
    return arrivals


def render_arrival(trace: Trace, alert: bool) -> str:
    """One line: flag, id, outcome, task — the readable minimum."""
    flag = "!! FAIL" if trace.success is False else "  ok  "
    if alert:
        flag = ">> ALERT"
    task = " ".join(str(trace.task or "").split())
    if len(task) > 56:
        task = task[:53] + "..."
    steps = len(trace.steps)
    tokens = sum(s.tokens for s in trace.steps)
    burn = f" {tokens:,}tok" if tokens else ""
    return (f"{flag} {trace.id} [{steps} steps]{burn} {task}")


def arrival_payload(trace: Trace) -> dict:
    """The signed-channel body for a failed arrival — the same
    fields a receiver already knows from fleet payloads, scoped to
    one run."""
    return {
        "kind": "trace_failure",
        "trace": {
            "id": trace.id,
            "task": trace.task,
            "model": trace.model,
            "success": trace.success,
            "steps": len(trace.steps),
            "tokens": sum(s.tokens for s in trace.steps),
            "created_at": trace.created_at,
        },
        "announced_at": time.time(),
    }


def tail(store: Any, once: bool = False, interval: float = 5.0,
         max_passes: Optional[int] = None,
         announce_failure_url: Optional[str] = None,
         announce_hook: Optional[Any] = None) -> List[str]:
    """Watch arrivals; returns the printed lines (so tests and
    ``--once`` can assert instead of sleep).

    ``announce_failure_url`` fires the signed webhook on each failed
    arrival via ``announce_hook`` (the fleet's ``notify_webhook`` —
    injected so the channel logic stays in one place). The tail
    never dies from a webhook failure: the announcement is logged as
    a line and the watch continues.
    """
    from .store import trace_files

    seen: Set[str] = {p.stem for p in trace_files(store.directory)}
    lines: List[str] = [(f"tail: {len(seen)} trace(s) already on "
                         "file; watching for arrivals")]
    passes = 0
    while True:
        arrivals = scan_pass(store, seen)
        for trace in arrivals:
            failed = trace.success is False
            if failed and announce_failure_url and announce_hook:
                try:
                    status = announce_hook(
                        [], announce_failure_url,
                        payload=arrival_payload(trace))
                    lines.append(f"   webhook: {status}")
                except Exception as exc:  # nosec B110 - the watch
                    lines.append(f"   webhook failed: {exc}")
                    # must not die from an announcement failure
            lines.append(render_arrival(trace, alert=failed))
        if once:
            break
        passes += 1
        if max_passes is not None and passes >= max_passes:
            break
        time.sleep(interval)
    return lines
