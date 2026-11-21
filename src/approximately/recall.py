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

import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

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


_UTC = False


def set_utc(enabled: bool) -> None:
    """Read the memory in UTC instead of the machine's zone: two
    operators in different timezones reading the same store get
    the SAME day bucketing, and the day names survive a move."""
    global _UTC
    _UTC = bool(enabled)


def _local_day(ts: float) -> str:
    """The conversation's calendar day — the days the human
    actually lived (the machine's zone), or UTC when the door was
    asked for deterministic bucketing."""
    try:
        stamp = (datetime.fromtimestamp(ts, timezone.utc)
                 if _UTC else datetime.fromtimestamp(ts))
        return stamp.strftime("%Y-%m-%d")  # type: ignore[union-attr]
    except (OverflowError, OSError, ValueError):
        return "unknown"


def _local_time(ts: float) -> str:
    try:
        stamp = (datetime.fromtimestamp(ts, timezone.utc)
                 if _UTC else datetime.fromtimestamp(ts))
        return stamp.strftime("%H:%M")  # type: ignore[union-attr]
    except (OverflowError, OSError, ValueError):
        return "??:??"


def _finite_stamp(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    f = float(value)
    return f if math.isfinite(f) and f > 0 else None


_DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def valid_day(text: Any) -> bool:
    """``--day`` names ONE local calendar day (``YYYY-MM-DD``): the
    drill-down step from the summary to that day's conversations.
    A shape-valid impossible date (month 13) is still garbage."""
    if not isinstance(text, str) or not _DAY_RE.fullmatch(text):
        return False
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _in_window(trace: Trace, since: Optional[float],
               until: Optional[float], model: Optional[str],
               outcomes: str, day: Optional[str] = None) -> bool:
    """The time window plus the outcome/model filters: `outcomes`
    is "all", "ok" or "failed" — a human looks for the runs that
    went wrong, or for the ones that worked."""
    stamp = _finite_stamp(trace.created_at)
    if ((since is not None or until is not None)
            and (stamp is None or stamp < (since or 0)
                 or (until is not None and stamp > until))):
        return False
    if day is not None and _local_day(stamp or 0) != day:
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
                  outcomes: str = "all",
                  day: Optional[str] = None) -> List[Trace]:
    return [t for t in traces
            if _in_window(t, since, until, model, outcomes, day)]


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
    not two. A duplicate is counted, and if the two copies carry
    DIFFERENT content the id is named as diverged: two boxes
    holding two histories of one conversation is exactly the
    sync-conflict the ledger exists to catch, and silently
    keeping one side would read the conflict away."""
    def __init__(self) -> None:
        self._stores: List[Any] = []
        self._names: List[str] = []
        self.seen_again = 0
        self.diverged: List[str] = []

    def add(self, store: Any, name: Optional[str] = None) -> None:
        self._stores.append(store)
        self._names.append(name
                           or str(getattr(store, "directory", "")))

    @property
    def names(self) -> List[str]:
        return list(self._names)

    @property
    def duplicates(self) -> dict:
        return {"seen_again": self.seen_again,
                "diverged": list(self.diverged)}

    def list_traces(self, **kw: Any) -> List[Any]:
        # the counters describe THIS scan: each enumeration
        # rebuilds them, so a payload's counts always match the
        # scan that produced it
        self.seen_again = 0
        self.diverged = []
        seen: Dict[str, Any] = {}
        traces: List[Any] = []
        for store, name in zip(self._stores, self._names,
                               strict=True):
            label = Path(name).name or name
            for trace in store.list_traces(**kw):
                first = seen.get(trace.id)
                if first is None:
                    seen[trace.id] = trace
                    traces.append(_Tagged(trace, label))
                    continue
                self.seen_again += 1
                if (json.dumps(first.to_dict(), sort_keys=True)
                        != json.dumps(trace.to_dict(),
                                      sort_keys=True)
                        and trace.id not in self.diverged):
                    self.diverged.append(trace.id)
        return traces


class _Queried:
    """A store (or fleet view) seen through a query-DSL predicate.

    One wrap point gives every memory door the shared expression
    language: ``recall --query "success == false and created > 24h
    ago"`` reads the same timeline, search, summary and digest —
    of the selection, not the whole box. The predicate compiles
    once per door call; everything the wrapped view offers besides
    listing passes through untouched, so fleet conflict counts and
    store labels survive the wrap.
    """

    def __init__(self, inner: Any, pred: Callable[[Any], bool]):
        self._inner = inner
        self._pred = pred

    def list_traces(self, **kw: Any) -> List[Any]:
        return [t for t in self._inner.list_traces(**kw)
                if self._pred(t)]

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


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


def duplicate_note(dup: dict) -> str:
    """One line for the fleet view's conflicts: the same trace id
    read again, and which ids DIVERGED (two boxes hold two
    histories of one conversation)."""
    note = (f"note: {dup['seen_again']} conversation(s) were "
            "read again from later stores")
    diverged = dup.get("diverged") or []
    if diverged:
        shown = ", ".join(diverged[:3])
        more = (f" (+{len(diverged) - 3} more)"
                if len(diverged) > 3 else "")
        note += (f"; {len(diverged)} DIVERGED (two boxes hold "
                 f"different histories): {shown}{more}")
    return note


def _with_dup(store: Any, payload: dict) -> dict:
    """Attach the fleet view's conflict counts when the store
    reports any diverged id."""
    dup = _dup_payload(store)
    if dup:
        payload["duplicates"] = dup
    return payload


def _dup_payload(store: Any) -> Optional[dict]:
    """The fleet view's conflict counts, when the store reports
    them and any id DIVERGED. An identical copy is one memory —
    the dedupe working, not a conflict worth machinery."""
    dup = getattr(store, "duplicates", None)
    if dup and dup.get("diverged"):
        return dup
    return None


def timeline(store: Any, since: Optional[float] = None,
             until: Optional[float] = None,
             limit: Optional[int] = None,
             model: Optional[str] = None,
             outcomes: str = "all",
             day: Optional[str] = None) -> dict:
    """The conversations in the order they happened, grouped by
    the day they happened on — the machine's answer to "what did
    I even talk about last week?\"."""
    traces = _steps_window(store.list_traces(), since, until,
                           model=model, outcomes=outcomes, day=day)
    entries = sorted((_entry(t) for t in traces),
                     key=lambda e: (e["created_at"] or 0, e["id"]))
    if limit is not None:
        entries = entries[-limit:] if limit > 0 else []
    days: Dict[str, List[dict]] = {}
    for entry in entries:
        days.setdefault(entry["day"], []).append(entry)
    return _with_dup(store, {
        "conversations": len(entries),
        "days": [{"day": day, "entries": days[day]}
                 for day in sorted(days)]})


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
           outcomes: str = "all",
           day: Optional[str] = None) -> dict:
    """Find the conversations where something was said — every
    field a conversation speaks through, with a readable excerpt
    of the moment. Case-insensitive; newest last."""
    needle = " ".join(needle.split())
    if not needle:
        raise ValueError("search needs something to look for")
    traces = _steps_window(store.list_traces(), since, until,
                           model=model, outcomes=outcomes, day=day)
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
    return _with_dup(store, {
        "query": needle, "traces_scanned": len(traces),
        "hits": len(hits), "results": hits})


def _keywords(texts: List[str], top: int = 6) -> List[Tuple[str, int]]:
    """What the conversations were about, by frequency: latin words
    of three letters or more plus CJK bigrams (no dependencies, no
    magic) — stopwords from the pile."""
    counts: Counter = Counter()
    for raw in texts:
        text = str(raw or "").lower()
        for word in re.findall(r"[a-z][a-z0-9._-]{2,}", text):
            if word in _STOPWORDS or len(word) > 32:
                # a 200KB "word" is data blobbed into the task
                # line, not a topic: keywords name what the run
                # was ABOUT, and nothing about it is 33+ chars
                continue
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
              outcomes: str = "all",
              day: Optional[str] = None) -> dict:
    """The day-by-day answer: how many conversations, what they
    were about (top topics), which tools carried them, how many
    ended badly — the human-memory view of the store."""
    traces = _steps_window(store.list_traces(), since, until,
                           model=model, outcomes=outcomes, day=day)
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
    return _with_dup(store, {
        "conversations": len(traces),
        "failed": failed_total,
        "tokens": total_tokens,
        "tool_calls": total_tool_calls,
        "topics": _keywords(all_tasks, top=10),
        "days": day_rows,
    })


def _failure_row(trace: Trace) -> dict:
    """One failed conversation as the digest wants it: when, what,
    where it broke (the first error excerpt), and which failure
    modes the rule detectors name."""
    from .detectors import run_rules

    entry = _entry(trace)
    error_excerpt = None
    for step in trace.steps:
        if getattr(step, "error", None):
            error_excerpt = _excerpt(str(step.error), "")
            break
    modes = [{"mode_id": det.mode_id,
              "step_index": det.step_index,
              "evidence": det.evidence[0] if det.evidence else ""}
             for det in run_rules(trace)]
    return {**entry, "error_excerpt": error_excerpt,
            "modes": modes}


def digest(store: Any, since: Optional[float] = None,
           until: Optional[float] = None,
           model: Optional[str] = None,
           outcomes: str = "all",
           day: Optional[str] = None) -> dict:
    """The weekly postmortem of the conversations: the day rows,
    then the failed runs with their error excerpts and the modes
    the rule detectors name - what went wrong, when, and (the
    attribution layer's answer) how."""
    summary = summarize(store, since=since, until=until,
                        model=model, outcomes=outcomes, day=day)
    failed = _steps_window(store.list_traces(), since, until,
                           model=model, outcomes="failed", day=day)
    failed.sort(key=lambda t: (t.created_at or 0, t.id))
    rows = [_failure_row(t) for t in failed]
    payload = {**summary, "failures": rows}
    recurring = _recurring_modes(rows)
    if recurring:
        payload["recurring"] = recurring
    return _with_dup(store, payload)


def _digest_failure_lines(row: dict) -> List[str]:
    """One failed conversation's digest block: when, what, the
    modes, the moment it broke."""
    mark = _mark(row["success"])
    store = (" {" + str(row["store"]) + "}"
             if row.get("store") else "")
    head = (f"  {row['day']} {row['time']}  {mark}  "
            f"{row['task'][:72]}{store}")
    lines = [head]
    if row.get("modes"):
        named = ", ".join(
            f"{m['mode_id']} @step {m['step_index']}"
            for m in row["modes"][:4])
        lines.append(f"    modes: {named}")
    if row.get("error_excerpt"):
        lines.append(f"    [error] {row['error_excerpt']}")
    return lines


def _recurring_modes(rows: List[dict]) -> List[dict]:
    """The modes that keep coming back: a mode firing on failures
    across >= 2 distinct days is a pattern, not a one-off - the
    postmortem's headline is the pattern, not the accident."""
    by_mode: Dict[str, set] = {}
    for row in rows:
        for mode in row.get("modes") or []:
            by_mode.setdefault(mode["mode_id"], set()).add(
                row["day"])
    pairs = sorted(((mode_id, len(days))
                    for mode_id, days in by_mode.items()
                    if len(days) >= 2),
                   key=lambda p: (-p[1], p[0]))
    return [{"mode_id": mode_id, "days": days}
            for mode_id, days in pairs]


def render_digest(payload: dict) -> str:
    """The prose digest: the summary, then one failure a block -
    the run, its modes, and the moment it broke."""
    head = render_summary(payload)
    failures = payload.get("failures") or []
    if not failures:
        return head
    lines = [head, "", f"Failures ({len(failures)}):"]
    for row in failures:
        lines.extend(_digest_failure_lines(row))
    recurring = payload.get("recurring") or []
    if recurring:
        lines.append("")
        lines.append("Recurring:")
        lines.extend(
            f"  {row['mode_id']}: on {row['days']} day(s)"
            for row in recurring[:6])
    dup = payload.get("duplicates")
    if dup:
        lines.append(duplicate_note(dup))
    return "\n".join(lines)


def _task_keywords_of(trace: Trace) -> set:
    """The task's content words, lower-cased: the topic signal the
    related scorer uses."""
    words = re.findall(r"[a-z][a-z0-9._-]{2,}",
                       str(trace.task or "").lower())
    return {w for w in words if w not in _STOPWORDS
            and len(w) <= 32}


def _find_trace(store: Any, trace_id: str) -> Optional[Trace]:
    for trace in store.list_traces():
        if trace.id == trace_id:
            return trace
    return None


def _score_pair(trace: Trace, target_tools: set,
                target_words: set, target_day: str) -> dict:
    """One candidate's relatedness components: shared tools (a
    Jaccard), shared task topics, the same calendar day."""
    tools = {s.tool for s in trace.steps
             if s.kind == "tool_call" and s.tool}
    words = _task_keywords_of(trace)
    day = _local_day(_finite_stamp(trace.created_at) or 0)
    union = tools | target_tools
    tool_score = (len(tools & target_tools) / len(union)
                  if union else 0.0)
    word_union = words | target_words
    topic_score = (len(words & target_words) / len(word_union)
                   if word_union else 0.0)
    score = tool_score + topic_score \
        + (0.5 if day == target_day else 0.0)
    return {"score": score,
            "shared_tools": bool(tools & target_tools),
            "shared_topic": bool(words & target_words),
            "same_day": day == target_day}


def related(store: Any, trace_id: str, limit: int = 5,
            since: Optional[float] = None,
            until: Optional[float] = None) -> dict:
    """From one conversation, the related ones: scored by shared
    tools (a Jaccard), shared task topics, and the same calendar
    day - deterministic (score desc, then id) so the answer never
    reshuffles between calls. The trace itself never ranks."""
    target = _find_trace(store, trace_id)
    if target is None:
        raise ValueError(f"no such trace: {trace_id}")
    scored = _scored_candidates(store, target)
    scored.sort(key=lambda s: (-s[0], s[1]))
    windowed = [s for s in scored
                if _in_window(s[2], since, until, None, "all")]
    return {"trace": trace_id,
            "related": len(windowed[:max(0, int(limit))]),
            "results": _related_results(windowed, limit)}


def _scored_candidates(store: Any, target: Trace) -> list:
    """Every other trace that shares anything with the target:
    (score, id, trace, verdict) tuples, score > 0 only."""
    target_tools = {s.tool for s in target.steps
                    if s.kind == "tool_call" and s.tool}
    target_words = _task_keywords_of(target)
    target_day = _local_day(_finite_stamp(target.created_at) or 0)
    scored = []
    for trace in store.list_traces():
        if trace.id == target.id:
            continue
        verdict = _score_pair(trace, target_tools, target_words,
                              target_day)
        if verdict["score"] > 0:
            scored.append((verdict["score"], trace.id, trace,
                           verdict))
    return scored


def _related_results(windowed: list, limit: int) -> list:
    """The rendered entries: score, then the reasons the score
    was earned (shared tools / shared topic / same day)."""
    results = []
    for score, _tid, trace, verdict in windowed[:max(0, int(limit))]:
        entry = _entry(trace)
        entry["score"] = round(score, 3)
        entry["reasons"] = [name for name, flag in
                            (("shared tools",
                              verdict["shared_tools"]),
                             ("shared topic",
                              verdict["shared_topic"]),
                             ("same day", verdict["same_day"]))
                            if flag]
        results.append(entry)
    return results


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
    dup = _dup_payload(store)
    if dup:
        text += f"\n{duplicate_note(dup)}\n"
    from .store import atomic_write

    atomic_write(output, text)
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
