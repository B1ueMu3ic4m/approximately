"""Recall: what did I talk about with the AI — searchable, summed,
on a timeline.

Long conversations evaporate: weeks later nobody remembers what
was asked, what was decided, or where that one solution lived.
The store already records every run faithfully — this module turns
it back into memory: a chronological timeline of conversations, a
search that finds the moment something was said (with the
excerpt), and a day-by-day summary of topics, tools and outcomes.
Zero dependencies; nothing leaves the machine.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .trace import Trace

_EXCERPT = 160
_TIME_RE = re.compile(r"\S+")

# the searcher walks every field a conversation speaks through
# (task is the header probe's own field)
SEARCH_FIELDS = ("task", "result", "thought", "error", "final_output")
_STEP_FIELDS = tuple(f for f in SEARCH_FIELDS if f != "task")

_STOPWORDS = frozenset(["a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from", "has", "have", "how", "i", "in", "is", "it", "its", "me", "my", "no", "not", "of", "on", "or", "so", "that", "the", "then", "this", "to", "was", "we", "what", "when", "where", "which", "who", "why", "will", "with", "you", "your", "do", "did", "done", "can", "cannot", "about", "after", "all", "also", "any", "because", "been", "before", "being", "between", "both", "during", "each", "else", "every", "few", "first", "get", "got", "if", "into", "just", "like", "made", "make", "many", "more", "most", "much", "need", "next", "now", "only", "other", "our", "out", "over", "own", "same", "should", "since", "some", "still", "such", "take", "than", "them", "there", "these", "they", "those", "through", "too", "under", "until", "up", "use", "used", "very", "want", "way", "well", "were", "while", "who's", "why's", "yet"])

_CJK = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")

# the grams that carry no topic: question words, pronouns, fillers
_CJK_STOP_GRAMS = frozenset(["什么", "怎么", "怎样", "这个", "那个", "如何", "可以", "我们", "你们", "他们", "自己", "一个", "一些", "就是", "但是", "然后", "所以", "如果", "因为", "应该", "可能", "或者", "以及", "这样", "那样", "没有还是"])


def _local_day(ts: float) -> str:
    """The conversation's local calendar day — memory is kept in
    the days the human actually lived."""
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        return "unknown"


def _local_time(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%H:%M")
    except (OverflowError, OSError, ValueError):
        return "??:??"


def _finite_stamp(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    f = float(value)
    return f if math.isfinite(f) and f > 0 else None


def _in_window(trace: Trace, since: Optional[float],
               until: Optional[float], model: Optional[str],
               outcomes: str) -> bool:
    """The time window plus the outcome/model filters: `outcomes`
    is "all", "ok" or "failed" — a human looks for the runs that
    went wrong, or for the ones that worked."""
    stamp = _finite_stamp(trace.created_at)
    if ((since is not None or until is not None)
            and (stamp is None or stamp < (since or 0)
                 or (until is not None and stamp > until))):
        return False
    if model and model.lower() not in \
            str(trace.model or "").lower():
        return False
    if outcomes == "ok":
        return trace.success is True
    if outcomes == "failed":
        return trace.success is False
    return True


def _steps_window(traces: Iterable[Trace], since: Optional[float],
                  until: Optional[float], model: Optional[str] = None,
                  outcomes: str = "all") -> List[Trace]:
    return [t for t in traces
            if _in_window(t, since, until, model, outcomes)]


def _step_totals(steps: list) -> Tuple[int, int]:
    """(tool_calls, finite duration ms) for one conversation."""
    tool_calls = 0
    duration = 0.0
    for step in steps:
        if step.kind == "tool_call":
            tool_calls += 1
        ms = getattr(step, "latency_ms", None)
        if isinstance(ms, (int, float)) and math.isfinite(ms):
            duration += float(ms or 0)
    return tool_calls, int(duration)


class _Tagged:
    """A trace with its store's name riding along — the fleet
    view's provenance, without mutating the loaded record."""
    __slots__ = ("_trace", "store")

    def __init__(self, trace: Trace, store: str) -> None:
        self._trace = trace
        self.store = store

    def __getattr__(self, name: str) -> Any:
        return getattr(self._trace, name)


class MultiStore:
    """Several stores read as one memory: the recall doors over a
    fleet of stores. Deduped by trace id (the first store wins) —
    the same conversation imported into two boxes is one memory,
    not two."""
    def __init__(self) -> None:
        self._stores: List[Any] = []
        self._names: List[str] = []

    def add(self, store: Any, name: Optional[str] = None) -> None:
        self._stores.append(store)
        self._names.append(name
                           or str(getattr(store, "directory", "")))

    @property
    def names(self) -> List[str]:
        return list(self._names)

    def list_traces(self, **kw: Any) -> List[Any]:
        seen: set = set()
        traces: List[Any] = []
        for store, name in zip(self._stores, self._names,
                               strict=True):
            label = Path(name).name or name
            for trace in store.list_traces(**kw):
                if trace.id in seen:
                    continue
                seen.add(trace.id)
                traces.append(_Tagged(trace, label))
        return traces


def _entry(trace: Trace) -> dict:
    """One conversation as the timeline wants it: when, what, how
    it went — no attribution runs, no heavy machinery."""
    stamp = _finite_stamp(trace.created_at)
    tool_calls, duration = _step_totals(trace.steps)
    entry = {
        "id": trace.id,
        "created_at": trace.created_at,
        "day": _local_day(stamp or 0),
        "time": _local_time(stamp or 0),
        "task": " ".join(str(trace.task or "").split()) or "(untitled)",
        "model": trace.model,
        "success": trace.success,
        "steps": len(trace.steps),
        "tool_calls": tool_calls,
        "duration_ms": duration,
        "tools": sorted({s.tool for s in trace.steps
                         if s.kind == "tool_call" and s.tool},
                        key=str),
    }
    store = getattr(trace, "store", None)
    if store:
        entry["store"] = store
    return entry


def timeline(store: Any, since: Optional[float] = None,
             until: Optional[float] = None,
             limit: Optional[int] = None,
             model: Optional[str] = None,
             outcomes: str = "all") -> dict:
    """The conversations in the order they happened, grouped by
    the day they happened on — the machine's answer to "what did
    I even talk about last week?\"."""
    traces = _steps_window(store.list_traces(), since, until,
                           model=model, outcomes=outcomes)
    entries = sorted((_entry(t) for t in traces),
                     key=lambda e: (e["created_at"] or 0, e["id"]))
    if limit is not None:
        entries = entries[-limit:] if limit > 0 else []
    days: Dict[str, List[dict]] = {}
    for entry in entries:
        days.setdefault(entry["day"], []).append(entry)
    return {"conversations": len(entries),
            "days": [{"day": day, "entries": days[day]}
                     for day in sorted(days)]}


def _excerpt(text: str, needle: str) -> str:
    """A readable window around the match — the moment it was
    said, not the whole log."""
    text = " ".join(str(text).split())
    lowered = text.lower()
    at = lowered.find(needle.lower())
    if at < 0:
        return text[:_EXCERPT]
    start = max(0, at - _EXCERPT // 2)
    end = min(len(text), start + _EXCERPT)
    prefix = "…" if start else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{text[start:end]}{suffix}"


def _step_matches(trace: Trace, needle: str,
                  cap: int = 8) -> List[dict]:
    lowered = needle.lower()
    matches: List[dict] = []
    task = " ".join(str(trace.task or "").split())
    if lowered in task.lower():
        matches.append({"step_index": None, "field": "task",
                        "excerpt": _excerpt(task, needle)})
    matches = _walk_step_fields(trace.steps, lowered, needle,
                                matches, cap)
    final = getattr(trace, "final_output", None)
    if final and lowered in str(final).lower() and len(matches) < cap:
        matches.append({"step_index": None, "field": "final_output",
                        "excerpt": _excerpt(final, needle)})
    return matches


def _walk_step_fields(steps: list, lowered: str, needle: str,
                      matches: List[dict], cap: int) -> List[dict]:
    for step in steps:
        for field in _STEP_FIELDS:
            value = getattr(step, field, None)
            if value is None or not str(value).strip():
                continue
            if lowered in str(value).lower():
                matches.append({"step_index": step.index,
                                "field": field,
                                "excerpt": _excerpt(value, needle)})
                if len(matches) >= cap:
                    return matches
    return matches


def search(store: Any, needle: str, since: Optional[float] = None,
           until: Optional[float] = None, limit: int = 20,
           model: Optional[str] = None,
           outcomes: str = "all") -> dict:
    """Find the conversations where something was said — every
    field a conversation speaks through, with a readable excerpt
    of the moment. Case-insensitive; newest last."""
    needle = " ".join(needle.split())
    if not needle:
        raise ValueError("search needs something to look for")
    traces = _steps_window(store.list_traces(), since, until,
                           model=model, outcomes=outcomes)
    traces.sort(key=lambda t: (t.created_at or 0, t.id))
    hits = []
    for trace in traces:
        matches = _step_matches(trace, needle)
        if matches:
            entry = _entry(trace)
            hits.append({**entry, "matches": matches,
                         "match_count": len(matches)})
        if len(hits) >= limit:
            break
    return {"query": needle, "traces_scanned": len(traces),
            "hits": len(hits), "results": hits}


def _keywords(texts: List[str], top: int = 6) -> List[Tuple[str, int]]:
    """What the conversations were about, by frequency: latin words
    of three letters or more plus CJK bigrams (no dependencies, no
    magic) — stopwords from the pile."""
    counts: Counter = Counter()
    for raw in texts:
        text = str(raw or "").lower()
        for word in re.findall(r"[a-z][a-z0-9._-]{2,}", text):
            if word not in _STOPWORDS:
                counts[word] += 1
        for run in re.findall(r"[\u3400-\u9fff\uf900-\ufaff]+", text):
            # stop-grams are REMOVED before cutting: 怎么把 bigrammed
            # raw yields 么把/把重 — noise between the fence posts
            cleaned = run
            for stop in _CJK_STOP_GRAMS:
                cleaned = cleaned.replace(stop, "")
            for i in range(len(cleaned) - 1):
                counts[cleaned[i:i + 2]] += 1
    return counts.most_common(top)


def _day_tokens(traces: List[Trace]) -> int:
    return sum(s.tokens for t in traces for s in t.steps
               if isinstance(s.tokens, (int, float))
               and math.isfinite(s.tokens))


def _day_tool_rows(traces: List[Trace]) -> Tuple[int, List]:
    tool_calls = 0
    counts: Counter = Counter()
    for t in traces:
        for s in t.steps:
            if s.kind != "tool_call":
                continue
            tool_calls += 1
            if s.tool:
                counts[s.tool] += 1
    return tool_calls, counts.most_common(5)


def _store_names(traces: List[Trace]) -> List[str]:
    """The stores that carried these traces (fleet view only)."""
    return sorted({tag for tag in (getattr(t, "store", None)
                                   for t in traces) if tag},
                  key=str)


def _summarize_day(day: str, day_traces: List[Trace]) -> dict:
    """One day's memory row: conversations, topics, tools, outcomes."""
    traces = sorted(day_traces,
                    key=lambda t: (t.created_at or 0, t.id))
    tasks = [t.task or "(untitled)" for t in traces]
    failed = [t for t in traces if t.success is False]
    tool_calls, top_tools = _day_tool_rows(traces)
    row = {
        "day": day,
        "conversations": len(traces),
        "failed": len(failed),
        "tokens": _day_tokens(traces),
        "tool_calls": tool_calls,
        "topics": _keywords(tasks),
        "top_tools": top_tools,
        "titles": [{"id": t.id,
                    "task": " ".join(str(t.task or "").split())
                    or "(untitled)",
                    "success": t.success}
                   for t in traces],
    }
    stores = _store_names(traces)
    if stores:
        row["stores"] = stores
    return row


def summarize(store: Any, since: Optional[float] = None,
              until: Optional[float] = None,
              model: Optional[str] = None,
              outcomes: str = "all") -> dict:
    """The day-by-day answer: how many conversations, what they
    were about (top topics), which tools carried them, how many
    ended badly — the human-memory view of the store."""
    traces = _steps_window(store.list_traces(), since, until,
                           model=model, outcomes=outcomes)
    days: Dict[str, List[Trace]] = {}
    for trace in traces:
        stamp = _finite_stamp(trace.created_at)
        days.setdefault(_local_day(stamp or 0), []).append(trace)
    day_rows = []
    total_tokens = 0
    total_tool_calls = 0
    failed_total = 0
    for day in sorted(days):
        row = _summarize_day(day, days[day])
        day_rows.append(row)
        total_tokens += row["tokens"]
        total_tool_calls += row["tool_calls"]
        failed_total += row["failed"]
    all_tasks = [t.task or "(untitled)" for t in traces]
    return {
        "conversations": len(traces),
        "failed": failed_total,
        "tokens": total_tokens,
        "tool_calls": total_tool_calls,
        "topics": _keywords(all_tasks, top=10),
        "days": day_rows,
    }


def _mark(success: Any) -> str:
    return "✓" if success is True else "✗" if success is False \
        else "·"


def export_diary(store: Any, output: Path,
                 since: Optional[float] = None,
                 until: Optional[float] = None) -> dict:
    """The memory as a file: timeline then summary, one markdown
    diary a person can open months later. Returns the counts."""
    summary = summarize(store, since=since, until=until)
    payload = timeline(store, since=since, until=until)
    names = getattr(store, "names", None)
    head = "Conversation diary"
    if names:
        head += " — " + ", ".join(Path(n).name for n in names)
    text = (f"# {head}\n\n"
            f"{render_summary(summary)}\n\n"
            f"## Timeline\n\n{render_timeline(payload)}\n")
    import os

    tmp = output.with_name(output.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, output)
    return {"conversations": summary["conversations"],
            "days": len(summary["days"]),
            "path": str(output)}


def render_timeline(payload: dict) -> str:
    """The prose timeline: day headers, one conversation a line —
    the shape a human skims at 2am looking for last Tuesday."""
    lines: List[str] = []
    if not payload["conversations"]:
        return "no conversations in this window"
    for day in payload["days"]:
        entries = day["entries"]
        lines.append(f"{day['day']}  ({len(entries)} conversation"
                     f"{'s' if len(entries) != 1 else ''})")
        for e in entries:
            mark = _mark(e["success"])
            tools = f" [{', '.join(e['tools'][:3])}]" if e["tools"] else ""
            minutes = e["duration_ms"] / 60000.0
            dur = (f" {minutes:.0f}m" if minutes >= 1
                   else f" {e['duration_ms'] / 1000.0:.0f}s")
            store = (" {" + str(e["store"]) + "}"
                     if e.get("store") else "")
            lines.append(f"  {e['time']}  {mark}  {e['task'][:72]}"
                         f"{store}{tools}{dur}")
    return "\n".join(lines)


def render_summary(payload: dict) -> str:
    """The prose summary: totals, topics, then day by day — what
    was talked about, with the AI, when."""
    if not payload["conversations"]:
        return "no conversations in this window"
    lines = [(f"{payload['conversations']} conversation(s) · "
              f"{payload['failed']} failed · "
              f"{payload['tool_calls']} tool calls · "
              f"{payload['tokens']:,} tokens")]
    topics = payload["topics"]
    if topics:
        lines.append("Top topics: " + ", ".join(
            f"{word} x{count}" for word, count in topics))
    for day in payload["days"]:
        lines.extend(_summary_day(day))
    return "\n".join(lines)


def _summary_day(day: dict) -> List[str]:
    failed_note = (f", {day['failed']} failed"
                   if day["failed"] else "")
    lines = [(f"\n{day['day']} — {day['conversations']} "
              f"conversation(s){failed_note}, "
              f"{day['tokens']:,} tokens")]
    if day.get("stores"):
        lines.append("  stores: " + ", ".join(day["stores"]))
    for label, pairs in (("about", day["topics"][:5]),
                         ("tools", day["top_tools"])):
        if pairs:
            lines.append(f"  {label}: " + ", ".join(
                f"{word} x{count}" for word, count in pairs))
    lines.extend(f"  {_mark(title['success'])} "
                 f"{title['task'][:76]}"
                 for title in day["titles"])
    return lines
