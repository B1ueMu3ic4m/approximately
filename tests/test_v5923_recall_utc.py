"""v5923: the memory reads the same way from every timezone.

The day bucketing used the machine's zone — an operator in Tokyo
and one in Berlin reading the SAME store saw different day rows,
and the day names moved when the store moved. ``--utc`` on the
memory doors (and utc=true on the MCP tool) buckets in UTC: two
operators in different timezones read the same store the same
way. The default stays the human's own zone — memory is kept in
the days the human actually lived.
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "approximately", *args],
        capture_output=True, text=True, cwd=str(ROOT),
        encoding="utf-8")


def _convo(tmp_path, name, task, created):
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    store = TraceStore(tmp_path / name)
    rec = Recorder(task, model="m/1", store=store, save=False)
    rec.tool("deploy", {}, result="ok")
    rec.respond("done", success=True)
    rec.trace.created_at = created
    store.save(rec.trace)
    return store


def test_utc_bucketing_matches_utc_days(tmp_path):
    # 23:30 UTC on one day and 00:30 UTC the next: the two
    # conversations sit in DIFFERENT UTC days no matter which
    # zone the machine runs in
    # a real UTC midnight: 23:30 UTC one day, 00:30 UTC the next
    midnight = 20741 * 86400  # 2026-10-15T00:00:00Z
    stamps = [midnight - 1800, midnight + 1800]
    tasks = ["before midnight utc", "after midnight utc"]
    for stamp, task in zip(stamps, tasks, strict=True):
        _convo(tmp_path, "s", task, stamp)
    store = tmp_path / "s"
    r = _run("--store", str(store), "recall", "--utc", "--json")
    payload = json.loads(r.stdout)
    days = [day["day"] for day in payload["days"]]
    expected = sorted({datetime.fromtimestamp(
        s, timezone.utc).strftime("%Y-%m-%d") for s in stamps})
    assert days == expected, (
        f"UTC bucketing must match the UTC calendar: {days} vs "
        f"{expected}")
    # each entry's day equals the UTC day of its own stamp
    for day_row in payload["days"]:
        for entry in day_row["entries"]:
            utc_day = datetime.fromtimestamp(
                entry["created_at"], timezone.utc).strftime(
                    "%Y-%m-%d")
            assert entry["day"] == utc_day


def test_local_bucketing_stays_the_default(tmp_path):
    stamp = 1792000000 - 1800
    _convo(tmp_path, "s", "near the local midnight", stamp)
    r = _run("--store", str(tmp_path / "s"), "recall", "--json")
    payload = json.loads(r.stdout)
    entry = payload["days"][-1]["entries"][0]
    from datetime import datetime as dt

    local_day = dt.fromtimestamp(entry["created_at"]).strftime(
        "%Y-%m-%d")
    assert entry["day"] == local_day, \
        "without --utc the days stay the human's own"


def test_the_summary_and_digest_honor_utc(tmp_path):
    midnight = 20741 * 86400  # 2026-10-15T00:00:00Z
    stamps = [midnight - 1800, midnight + 1800]
    tasks = ["before midnight utc", "after midnight utc"]
    for stamp, task in zip(stamps, tasks, strict=True):
        _convo(tmp_path, "s", task, stamp)
    store = tmp_path / "s"
    r = _run("--store", str(store), "recall-summary", "--utc",
             "--json")
    payload = json.loads(r.stdout)
    assert len(payload["days"]) == 2, \
        "the summary splits the UTC midnight like the timeline"
    out = tmp_path / "digest.md"
    r2 = _run("--store", str(store), "recall-digest", "--utc",
              "--export", str(out))
    assert r2.returncode == 0, r2.stderr
    text = out.read_text(encoding="utf-8")
    assert "before midnight utc" in text


def test_the_mcp_tool_gains_utc(tmp_path):
    from approximately.mcp_server import _TOOLS, ServerContext, handle_request

    recall = next(t for t in _TOOLS if t["name"] == "recall")
    assert "utc" in recall["inputSchema"]["properties"], \
        "a client cannot discover a door the schema hides"
    stamp = 20741 * 86400 - 1800  # 23:30 UTC the day before
    _convo(tmp_path, "s", "near the utc midnight", stamp)
    ctx = ServerContext(str(tmp_path / "s"))
    payload = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "recall",
                   "arguments": {"utc": True}},
    }, ctx)
    result = json.loads(payload["result"]["content"][0]["text"])
    utc_day = datetime.fromtimestamp(
        result["days"][-1]["entries"][0]["created_at"],
        timezone.utc).strftime("%Y-%m-%d")
    assert result["days"][-1]["day"] == utc_day, \
        "the wire buckets in UTC when asked"
