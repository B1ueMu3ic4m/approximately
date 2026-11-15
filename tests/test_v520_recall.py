"""v520: recall — what did I talk about with the AI.

Long conversations evaporate: weeks later nobody remembers what
was asked, what was decided, or where that one solution lived.
The store already records every run faithfully; recall turns it
back into memory — the conversation timeline grouped by day, a
search over every field a conversation speaks through (with the
readable excerpt of the moment), and the day-by-day summary of
topics, tools and outcomes. Zero dependencies; nothing leaves
the machine.
"""

import subprocess
import sys
import time
from pathlib import Path

from approximately.recall import (
    _keywords,
    render_summary,
    render_timeline,
    search,
    summarize,
    timeline,
)
from approximately.store import TraceStore
from approximately.trace import Trace

ROOT = Path(__file__).resolve().parent.parent

NOW = time.time()


def _store(tmp_path):
    from approximately.recorder import Recorder

    store = TraceStore(tmp_path)
    convs = [
        ("fix the retry backoff in the deploy pipeline", True,
         "deploy", 86400 * 2, 120),
        ("migrate the database to the new schema", False, "bash",
         3600, 240),
        ("design the recall feature for conversation memory", True,
         "plan", 0, 60),
    ]
    ids = []
    for i, (task, ok, tool, age, latency_ms) in enumerate(convs):
        rec = Recorder(task, store=store, save=False)
        rec.trace.created_at = NOW - age
        rec.tool(tool, {"cmd": "ls"}, result="ok" if ok else "boom",
                 latency_ms=latency_ms, tokens=100 + i * 50)
        rec.respond("gave up" if not ok else "done", success=ok)
        store.save(rec.trace, stamp=False)
        ids.append(rec.trace.id)
    return store, ids


# ---- the timeline: when, what, how it went

def test_the_timeline_groups_by_day_in_order(tmp_path):
    store, _ids = _store(tmp_path)
    payload = timeline(store)
    assert payload["conversations"] == 3
    days = [d["day"] for d in payload["days"]]
    assert days == sorted(days), "oldest day first"
    for day in payload["days"]:
        stamps = [e["created_at"] for e in day["entries"]]
        assert stamps == sorted(stamps), "oldest first inside a day"
    first = payload["days"][0]["entries"][0]
    assert first["task"] == ("fix the retry backoff in the "
                             "deploy pipeline")
    assert first["success"] is True
    assert first["tools"] == ["deploy"]


def test_the_timeline_window_filters(tmp_path):
    store, _ids = _store(tmp_path)
    recent = timeline(store, since=NOW - 86400 * 1.5)
    assert recent["conversations"] == 2, "the 2-day-old stays out"
    windowed = timeline(store, since=NOW - 2 * 86400,
                        until=NOW - 3600)
    assert windowed["conversations"] == 2, \
        "the oldest two inside the window; --until composes"
    limited = timeline(store, limit=2)
    assert limited["conversations"] == 2, \
        "limit keeps the NEWEST conversations"


def test_the_prose_timeline_is_skimmable(tmp_path):
    store, _ids = _store(tmp_path)
    text = render_timeline(timeline(store))
    assert "✓" in text and "✗" in text, "the outcome marks"
    assert "deploy" in text
    for day in ("2026-",):
        assert day in text
    assert "fix the retry backoff" in text


# ---- the search: find the moment something was said

def test_the_search_finds_step_results_with_excerpts(tmp_path):
    store, _ids = _store(tmp_path)
    payload = search(store, "retry backoff")
    assert payload["hits"] == 1
    hit = payload["results"][0]
    assert hit["matches"][0]["field"] == "task"
    assert "retry backoff" in hit["matches"][0]["excerpt"]


def test_the_search_walks_every_speaking_field(tmp_path):
    store, _ids = _store(tmp_path)
    trace = Trace.from_dict({
        "id": "abcd1234ef01", "task": "another conversation",
        "created_at": NOW - 3600,
        "final_output": "we discussed the schema migration",
        "steps": [
            {"kind": "plan", "thought": "think about indexes"},
            {"kind": "tool_call", "tool": "bash", "error": "boom "
             "on schema lock"},
        ]})
    store.save(trace, stamp=False)
    for needle, field in [("indexes", "thought"),
                          ("schema lock", "error"),
                          ("schema migration", "final_output")]:
        payload = search(store, needle)
        assert payload["hits"] == 1, f"{needle} must be findable"
        assert payload["results"][0]["matches"][0]["field"] == field


def test_an_empty_needle_is_refused(tmp_path):
    store, _ids = _store(tmp_path)
    try:
        search(store, "   ")
        raise AssertionError("an empty needle must be refused")
    except ValueError:
        pass


def test_the_search_door_prose_and_json(tmp_path):
    from approximately.cli import build_parser

    parser = build_parser()
    argv = parser.parse_args(["recall", "--grep", "retry",
                              "--since", "1d", "--json"])
    assert argv.grep == "retry" and argv.since is not None
    argv2 = parser.parse_args(["recall-summary", "--json"])
    assert argv2.json is True


# ---- the summary: topics, tools, outcomes, day by day

def test_the_summary_aggregates_days_topics_tools(tmp_path):
    store, _ids = _store(tmp_path)
    payload = summarize(store)
    assert payload["conversations"] == 3
    assert payload["failed"] == 1
    assert payload["tokens"] == 100 + 150 + 200
    assert payload["tool_calls"] == 3
    words = {w for w, _c in payload["topics"]}
    assert {"retry", "backoff", "deploy"} & words, \
        "the topics name what the conversations were about"
    day = payload["days"][0]
    assert day["top_tools"] == [("deploy", 1)]


def test_stopwords_never_become_topics():
    topics = _keywords(["what is the way to fix the thing it"])
    words = {w for w, _c in topics}
    assert not words & {"what", "the", "way", "it"}, \
        "stopwords used to drown the real topics"


def test_cjk_tasks_bigram_into_topics():
    topics = _keywords(["修复重试退避策略", "再次修复重试逻辑"])
    pairs = {w for w, _c in topics}
    assert any("\u91cd\u8bd5" in w for w in pairs), \
        "CJK conversations topic into character bigrams (retry)"


def test_the_prose_summary_reads_like_memory(tmp_path):
    store, _ids = _store(tmp_path)
    text = render_summary(summarize(store))
    assert "conversation" in text and "Top topics" in text
    assert "✗" in text, "the failed conversation is marked"
    assert "deploy x1" in text, "the tools that carried the day"


# ---- the doors end to end

def test_the_recall_door_reads_the_store(tmp_path):
    store, _ids = _store(tmp_path)
    r = subprocess.run(
        [sys.executable, "-m", "approximately", "--store",
         str(store.directory), "recall"],
        capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0 and "conversation" in r.stdout
    r = subprocess.run(
        [sys.executable, "-m", "approximately", "--store",
         str(store.directory), "recall", "--grep", "database"],
        capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0 and "schema" in r.stdout
    assert "[task]" in r.stdout or "[error" in r.stdout


def test_the_recall_door_answers_an_empty_store(tmp_path):
    r = subprocess.run(
        [sys.executable, "-m", "approximately", "--store",
         str(tmp_path), "recall"],
        capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0 and "no conversations" in r.stdout
    r = subprocess.run(
        [sys.executable, "-m", "approximately", "--store",
         str(tmp_path), "recall", "--grep", "anything"],
        capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 1 and "nothing found" in r.stdout


def test_the_summary_door_answers_an_empty_store(tmp_path):
    r = subprocess.run(
        [sys.executable, "-m", "approximately", "--store",
         str(tmp_path), "recall-summary"],
        capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0 and "no conversations" in r.stdout


def test_the_mcp_tool_speaks_the_same_shapes(tmp_path):
    from approximately.mcp_server import ServerContext, _tool_recall

    store, _ids = _store(tmp_path)
    ctx = ServerContext(store.directory)
    tl = _tool_recall(ctx, {})
    assert tl["conversations"] == 3
    hits = _tool_recall(ctx, {"grep": "retry"})
    assert hits["hits"] == 1
    summary = _tool_recall(ctx, {"summarize": True})
    assert summary["failed"] == 1
    recent = _tool_recall(ctx, {"since_days": 1})
    assert recent["conversations"] == 2, "since_days filters"
    limited = _tool_recall(ctx, {"limit": 1})
    assert limited["conversations"] == 1, "the newest one"


def test_the_tool_registry_stays_balanced():
    from approximately import mcp_server as m

    names = [t["name"] for t in m._TOOLS]
    assert "recall" in names and len(names) == len(m._HANDLERS), \
        "every advertised tool has a handler"
