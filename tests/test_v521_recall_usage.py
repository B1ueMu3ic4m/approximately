"""v521: recall meets its first real users.

The day-one walkthrough: an imported chat export flows into
recall (messages-list lines, CJK content); a typo'd store path
used to be silently created and answered "no conversations" —
to a human looking for last Tuesday that reads as lost memory;
CJK topic grams drowned in question-word noise (怎么把/么把);
and --limit -3 was silently accepted.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from approximately.importer import import_lines
from approximately.recall import _keywords, search, timeline
from approximately.store import TraceStore

ROOT = Path(__file__).resolve().parent.parent


def _run(*args, store=None):
    return subprocess.run(
        [sys.executable, "-m", "approximately",
         "--store", str(store if store is not None else tmp_store()),
         *args],
        capture_output=True, text=True, cwd=str(ROOT))


def tmp_store():
    return Path(tempfile.mkdtemp())


def test_an_imported_chat_export_flows_into_recall(tmp_path):
    store = TraceStore(tmp_path)
    lines = [json.dumps([{"role": "user",
                          "content": "怎么把重试退避改成指数的？"}]),  # noqa: RUF001
             json.dumps([{"role": "assistant",
                          "content": "使用指数退避"}])]
    import_lines(lines, store, fmt="messages-list")
    payload = timeline(store)
    assert payload["conversations"] == 2, \
        "imported chats are conversations too"
    hits = search(store, "指数退避")
    assert hits["hits"] == 1, "CJK content is searchable"
    assert "指数退避" in hits["results"][0]["matches"][0]["excerpt"]


def test_a_typo_store_path_is_a_refusal_not_lost_memory(tmp_path):
    r = _run("recall", store=tmp_path / "typo-store")
    assert r.returncode == 2,  (
        "silently creating an empty store and answering 'no  "
        "conversations' reads as lost memory to a human")
    assert "store not found" in r.stderr
    assert not (tmp_path / "typo-store").exists(), \
        "the refusal must not create the directory"
    r2 = _run("recall-summary", store=tmp_path / "typo-two")
    assert r2.returncode == 2 and "store not found" in r2.stderr


def test_real_stores_still_open(tmp_path):
    from approximately.recorder import Recorder

    store = TraceStore(tmp_path)
    rec = Recorder("real task", store=store)
    rec.tool("sh", {"cmd": "x"}, result="ok")
    rec.respond("done", success=True)
    store.save(rec.trace)
    r = _run("recall", store=store.directory)
    assert r.returncode == 0 and "real task" in r.stdout


def test_cjk_topics_name_the_subject_not_the_question_words():
    topics = _keywords(["怎么把重试退避改成指数的？",  # noqa: RUF001
                        "再次修复重试逻辑",
                        "重试还要考虑超时"])
    words = [w for w, _c in topics]
    assert words[0] == "重试",  (
        "the subject rises to the top; question-word grams  "
        "(怎么把/么把) used to drown it")
    assert "怎么" not in words[:3] and "么把" not in words[:3],  (
        "(么把 is gone entirely: stop-grams are removed before  "
        "the cut)")


def test_negative_limit_is_refused(tmp_path):
    r = _run("recall", "--limit", "-3", store=tmp_path)
    assert r.returncode == 2, \
        "a negative limit used to slice into silence"


def test_pure_conversations_render_without_tools(tmp_path):
    from approximately.recorder import Recorder

    store = TraceStore(tmp_path)
    rec = Recorder("pure chat about ideas", store=store)
    rec.plan("thinking about the design")
    rec.respond("done", success=True)
    store.save(rec.trace)
    payload = timeline(store)
    entry = payload["days"][0]["entries"][0]
    assert entry["tools"] == [],  (
        "a conversation with no tool calls still lands on the  "
        "timeline, tools column honestly empty")
    text = subprocess.run(
        [sys.executable, "-m", "approximately", "--store",
         str(store.directory), "recall"],
        capture_output=True, text=True, cwd=str(ROOT)).stdout
    assert "pure chat about ideas" in text


def test_mixed_type_tool_names_sort_by_str(tmp_path):
    from approximately.recorder import Recorder

    store = TraceStore(tmp_path)
    rec = Recorder("api-built junk", store=store)
    rec.trace.steps.append(
        __import__("approximately.trace", fromlist=["Step"]).Step(
            kind="tool_call", tool=7, result="ok"))
    rec.respond("done", success=True)
    store.save(rec.trace, stamp=False)
    payload = timeline(store)
    assert payload["conversations"] == 1, \
        "an int tool beside str tools used to TypeError the sort"
