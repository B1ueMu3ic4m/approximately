"""v580: the drill-down step, and the memory's user guide.

The memory loop had a missing link: recall-summary names a day,
and getting to THAT day's conversations meant --since/--until
arithmetic on a unix clock. ``--day YYYY-MM-DD`` names one local
calendar day across the timeline, the search and the summary
(the filter lives at the window predicate, so every filter -
model, outcome, fleet view, since/until - threads it), garbage
is refused at the flag boundary by name, and the MCP tool gains
the same key so the surfaces stay aligned. RECALL.md documents
the loop for the human who cannot find their own conversations
- the original complaint this feature family answers.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "approximately", *args],
        capture_output=True, text=True, cwd=str(ROOT))


def _convo(tmp_path, name, task, created, *, success=True):
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    store = TraceStore(tmp_path / name)
    rec = Recorder(task, model="m/1", store=store, save=False)
    rec.tool("deploy", {"env": name}, result="ok")
    rec.respond("done", success=success)
    rec.trace.created_at = created
    store.save(rec.trace)
    return store


def test_day_names_one_calendar_day(tmp_path):
    today = time.localtime()
    day = (f"{today.tm_year:04d}-{today.tm_mon:02d}-"
          f"{today.tm_mday:02d}")
    now = time.time()
    _convo(tmp_path, "s", "today's deployment", now)
    _convo(tmp_path, "s", "last month's report",
           now - 40 * 86400)
    r = _run("--store", str(tmp_path / "s"), "recall", "--day",
             day, "--json")
    payload = json.loads(r.stdout)
    tasks = [e["task"] for day_row in payload["days"]
             for e in day_row["entries"]]
    assert tasks == ["today's deployment"], (
        "the timeline showed everything in the store - the "
        "summary named a day and the drill-down had to do "
        "unix-clock arithmetic")
    assert payload["conversations"] == 1


def test_the_summary_day_is_the_drill_down(tmp_path):
    today = time.localtime()
    day = (f"{today.tm_year:04d}-{today.tm_mon:02d}-"
          f"{today.tm_mday:02d}")
    now = time.time()
    _convo(tmp_path, "s", "today's deployment", now)
    _convo(tmp_path, "s", "yesterday's outage", now - 86400,
           success=False)
    r = _run("--store", str(tmp_path / "s"), "recall-summary",
             "--day", day, "--json")
    payload = json.loads(r.stdout)
    assert [row["day"] for row in payload["days"]] == [day]
    assert payload["conversations"] == 1, \
        "the totals describe the drilled day, not the store"
    assert payload["failed"] == 0


def test_day_threads_the_filters_and_the_fleet(tmp_path):
    today = time.localtime()
    day = (f"{today.tm_year:04d}-{today.tm_mon:02d}-"
          f"{today.tm_mday:02d}")
    now = time.time()
    _convo(tmp_path, "box-a", "today's deployment", now)
    _convo(tmp_path, "box-b", "today's outage", now + 10,
           success=False)
    _convo(tmp_path, "box-b", "old failure", now - 5 * 86400,
           success=False)
    r = _run("recall", str(tmp_path / "box-a"),
             str(tmp_path / "box-b"), "--day", day,
             "--failed-only", "--json")
    payload = json.loads(r.stdout)
    tasks = [e["task"] for day_row in payload["days"]
             for e in day_row["entries"]]
    assert tasks == ["today's outage"], \
        "day + outcome + fleet view compose"
    assert all(e["store"] == "box-b" for e in
               payload["days"][0]["entries"]), \
        "the entries keep their store provenance"


def test_search_honors_the_day(tmp_path):
    today = time.localtime()
    day = (f"{today.tm_year:04d}-{today.tm_mon:02d}-"
          f"{today.tm_mday:02d}")
    now = time.time()
    _convo(tmp_path, "s", "today's deployment", now)
    _convo(tmp_path, "s", "the old deployment", now - 30 * 86400)
    r = _run("--store", str(tmp_path / "s"), "recall", "--grep",
             "deployment", "--day", day, "--json")
    payload = json.loads(r.stdout)
    assert payload["hits"] == 1, \
        "the search answers for the day asked about"
    assert payload["results"][0]["day"] == day


def test_garbage_day_is_refused_by_name(tmp_path):
    _convo(tmp_path, "s", "one run", time.time())
    for bad in ("2026-13-40", "yesterday", "20261117"):
        r = _run("--store", str(tmp_path / "s"), "recall",
                 "--day", bad)
        assert r.returncode == 2, (
            f"{bad!r} is not a calendar day: the flag boundary "
            "refuses it, never a silent empty answer")
        assert "YYYY-MM-DD" in r.stderr
        assert "Traceback" not in r.stderr
    r2 = _run("--store", str(tmp_path / "s"), "recall-summary",
              "--day", "not-a-day")
    assert r2.returncode == 2


def test_an_absent_day_is_an_honest_empty_answer(tmp_path):
    _convo(tmp_path, "s", "one run", time.time())
    r = _run("--store", str(tmp_path / "s"), "recall", "--day",
             "2024-01-01")
    assert r.returncode == 0, r.stderr
    assert "no conversations in this window" in r.stdout, (
        "a real date with nothing on it reads as empty, not as "
        "an error")


def test_the_mcp_tool_carries_day(tmp_path):
    from approximately.mcp_server import _TOOLS, ServerContext, handle_request

    recall = next(t for t in _TOOLS if t["name"] == "recall")
    assert "day" in recall["inputSchema"]["properties"]
    now = time.time()
    _convo(tmp_path, "s", "today's deployment", now)
    _convo(tmp_path, "s", "the old deployment", now - 30 * 86400)
    ctx = ServerContext(str(tmp_path / "s"))
    today = time.localtime()
    day = (f"{today.tm_year:04d}-{today.tm_mon:02d}-"
          f"{today.tm_mday:02d}")
    payload = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "recall", "arguments": {"day": day}},
    }, ctx)
    result = json.loads(payload["result"]["content"][0]["text"])
    assert result["conversations"] == 1
    bad = handle_request({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "recall", "arguments":
                   {"day": "someday"}},
    }, ctx)
    assert bad["result"]["isError"], \
        "the wire refuses a non-date the same way the CLI does"
