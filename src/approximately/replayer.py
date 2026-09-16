"""Replayer: re-run a recorded trajectory and diff it against the recording.

An :term:`Executor` is any callable ``Callable[[Step], str]`` that performs a
recorded step and returns its result text (raise to record an error). Replays
answer the postmortem question "does this still happen?" and enable A/B
comparison between the original executor and a patched one.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .trace import TOOL_CALL, Step, Trace

Executor = Callable[[Step], str]

REPRODUCED = "reproduced"
DIVERGED = "diverged"
CONSISTENT = "consistent"


@dataclass
class StepDiff:
    index: int
    kind: str
    tool: Optional[str]
    recorded: str
    replayed: str
    error: Optional[str]
    similarity: float
    match: bool

    @property
    def headline(self) -> str:
        head = self.tool or self.kind
        if self.error:
            return f"#{self.index} {head}: ERROR {self.error}"
        if not self.match:
            return (
                f"#{self.index} {head}: diverged "
                f"(similarity {self.similarity:.2f})"
            )
        return f"#{self.index} {head}: ok"


@dataclass
class ReplayDiff:
    trace_id: str
    steps: List[StepDiff] = field(default_factory=list)
    match_rate: float = 0.0
    verdict: str = CONSISTENT

    def summary(self) -> str:
        lines = [
            (f"replay {self.trace_id}: {self.verdict} "
            f"({sum(1 for s in self.steps if s.match)}/{len(self.steps)} steps match)")
        ]
        lines += ["  " + s.headline for s in self.steps if not s.match]
        return "\n".join(lines)


def compare(a: ReplayDiff, b: ReplayDiff) -> str:
    """Summarize an A/B replay: original executor *a* vs patched executor *b*."""
    flips = []
    for sa, sb in zip(a.steps, b.steps):
        if sa.match != sb.match:
            state = "now matches" if sb.match else "now diverges"
            flips.append(f"  step #{sa.index} ({sb.tool or sb.kind}): {state}")
    lines = [
        (f"A/B replay: {a.verdict} -> {b.verdict} "
        f"(match rate {a.match_rate:.0%} -> {b.match_rate:.0%})")
    ]
    if flips:
        lines.append("changed steps:")
        lines.extend(flips)
    else:
        lines.append("  no per-step changes")
    return "\n".join(lines)


def _similarity(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _replay_steps(trace: Trace, executor: Executor, threshold: float,
                  only_tool_calls: bool) -> tuple:
    """Run every eligible step; returns (diffs, reproduced_failure, all_match)."""
    diffs: List[StepDiff] = []
    reproduced_failure = False
    all_match = True
    for step in trace.steps:
        if only_tool_calls and step.kind != TOOL_CALL:
            continue
        diff, reproduced = _replay_one(step, executor, threshold)
        reproduced_failure = reproduced_failure or reproduced
        all_match = all_match and diff.match
        diffs.append(diff)
    return diffs, reproduced_failure, all_match


_REPLAY_CSS = """
body { font: 15px/1.55 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
       margin: 0; background: #f6f7f9; color: #1a1d21; }
main { max-width: 920px; margin: 0 auto; padding: 32px 20px 64px; }
h1 { font-size: 24px; margin: 0 0 4px; }
.meta { color: #6c757d; font-size: 13px; margin-bottom: 20px; }
.badge { display: inline-block; font-size: 12px; font-weight: 700; padding: 4px 12px;
         border-radius: 999px; }
.badge.ok { background: #def7e5; color: #1c7430; }
.badge.bad { background: #fde8e8; color: #b02a37; }
table { width: 100%; border-collapse: collapse; background: #fff;
        border: 1px solid #e4e7eb; border-radius: 12px; font-size: 13px; }
th { text-align: left; color: #868e96; font-weight: 600; padding: 7px 9px;
     border-bottom: 2px solid #e4e7eb; }
td { padding: 6px 9px; border-bottom: 1px solid #eef0f2; vertical-align: top; }
tr.diverged td { background: #fff3bf66; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
footer { margin-top: 22px; color: #adb5bd; font-size: 12.5px; text-align: center; }
"""


def render_replay_html(diff: "ReplayDiff",
                       b_diff: Optional["ReplayDiff"] = None) -> str:
    """Self-contained HTML A/B replay page (no JS, no CDN).

    Without ``b_diff``: one table, recorded vs replayed per step.
    With it: a third column showing the patched executor's result, so
    the A/B decision is one scroll.
    """
    import datetime
    import html as _html

    esc = _html.escape
    status_cls = "ok" if diff.verdict != DIVERGED else "bad"
    extra_head = (
        "<th>patched executor</th>" if b_diff is not None else "")
    rows = []
    b_by_index = {s.index: s for s in b_diff.steps} if b_diff else {}
    for step in diff.steps:
        cls = "" if step.match else ' class="diverged"'
        replayed = esc(step.replayed or step.error or "-")
        patched = ""
        if b_diff is not None:
            b = b_by_index.get(step.index)
            patched = esc((b.replayed or b.error or "-")[:120]) if b else "-"
        rows.append(
            f"<tr{cls}><td class=\"mono\">{step.index}</td>"
            f"<td class=\"mono\">{esc(step.tool or step.kind)}</td>"
            f"<td>{esc(step.recorded[:120])}</td>"
            f"<td>{replayed[:120]}</td>{('<td>' + patched + '</td>') if b_diff is not None else ''}"
            f"<td class=\"mono\">{step.similarity:.2f}</td></tr>"
        )
    rows_html = "".join(rows)
    b_meta = (f" · A/B vs {esc('patched executor')}" if b_diff else "")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>approximately · replay {esc(diff.trace_id)}</title>
<style>{_REPLAY_CSS}</style></head><body><main>
<h1>Replay A/B</h1>
<div class="meta">trace {esc(diff.trace_id)} · {len(diff.steps)} steps ·
match rate {diff.match_rate:.0%} · {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}{b_meta}</div>
<span class="badge {status_cls}">{esc(diff.verdict)}</span>
<p></p>
<table>
<tr><th>#</th><th>tool</th><th>recorded</th><th>replayed</th>{extra_head}<th>similarity</th></tr>
{rows_html}
</table>
<footer>generated by <a href="https://github.com/B1ueMu3ic4m/approximately">approximately</a></footer>
</main></body></html>"""


def replay(
    trace: Trace,
    executor: Executor,
    threshold: float = 0.85,
    only_tool_calls: bool = True,
) -> ReplayDiff:
    """Re-execute every recorded step through *executor* and diff results.

    Steps whose execution raises are recorded as errors on that step and make
    the replay diverge. ``verdict`` is ``reproduced`` when a step that errored
    in the recording errors again at the same index, ``consistent`` when all
    steps match, ``diverged`` otherwise.
    """
    diffs, reproduced_failure, all_match = _replay_steps(
        trace, executor, threshold, only_tool_calls)

    match_rate = (sum(1 for d in diffs if d.match) / len(diffs)) if diffs else 1.0
    if reproduced_failure:
        verdict = REPRODUCED
    elif all_match:
        verdict = CONSISTENT
    else:
        verdict = DIVERGED
    return ReplayDiff(trace_id=trace.id, steps=diffs,
                      match_rate=match_rate, verdict=verdict)


def _replay_one(step: Step, executor: Executor,
                threshold: float) -> tuple:
    """Execute one recorded step and diff it. Returns (diff, reproduced)."""
    try:
        value = executor(step)
        error = None
    except Exception as exc:
        value = ""
        error = f"{type(exc).__name__}: {exc}"
    recorded_text = step.error or step.result
    similarity = _similarity(recorded_text, value if error is None else "")
    match = error is None and similarity >= threshold
    reproduced = bool(step.error) and error is not None
    if reproduced:
        match = True  # same failure at the same step = faithful replay
    diff = StepDiff(
        index=step.index,
        kind=step.kind,
        tool=step.tool,
        recorded=recorded_text,
        replayed=value if error is None else error,
        error=error,
        similarity=similarity,
        match=match,
    )
    return diff, reproduced
