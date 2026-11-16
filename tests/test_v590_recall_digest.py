"""v590: the weekly postmortem of the conversations.

The memory family answered "what did I talk about" and "where was
it said" - but the question behind both is "what went wrong, when,
and how": a human reviewing a week of agent runs wants the failed
conversations with the moment they broke AND the failure modes
the attribution layer names, not a lookup they have to assemble
by hand. ``recall-digest`` joins the day rows with the failures:
each failed run carries its error excerpt (the moment it broke)
and the modes the rule detectors name - recall and attribution
finally in one answer. The fleet view threads it (store tags,
divergences); the day/outcome/model filters compose; the MCP tool
gains ``digest=true`` so the surfaces stay aligned (the v5.7.1
lesson applied the same round).
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


def _convo(tmp_path, name, task, *, success=True, result="ok",
           error=None, created=None):
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    store = TraceStore(tmp_path / name)
    rec = Recorder(task, model="m/1", store=store, save=False)
    rec.tool("deploy", {"env": name}, result=result, error=error)
    rec.respond("done", success=success)
    if created is not None:
        rec.trace.created_at = created
    store.save(rec.trace)
    return store


def test_the_digest_names_the_modes_of_a_failure(tmp_path):
    _convo(tmp_path, "s", "deploy the service", success=False,
           result=None, error="connection refused after 3 tries")
    r = _run("--store", str(tmp_path / "s"), "recall-digest")
    assert r.returncode == 0, r.stderr
    assert "Failures (1):" in r.stdout
    assert "[error]" in r.stdout and "connection refused" in \
        r.stdout, "the digest shows the moment it broke"
    assert "modes:" in r.stdout, \
        "the attribution layer's answer rides the same report"


def test_a_clean_window_has_no_failures_section(tmp_path):
    _convo(tmp_path, "s", "deploy the service", success=True)
    r = _run("--store", str(tmp_path / "s"), "recall-digest")
    assert r.returncode == 0 and "Failures" not in r.stdout


def test_the_json_shape_carries_both_layers(tmp_path):
    _convo(tmp_path, "s", "deploy the service", success=False,
           result=None, error="boom after 3 tries")
    r = _run("--store", str(tmp_path / "s"), "recall-digest",
             "--json")
    payload = json.loads(r.stdout)
    assert payload["failures"], "the failures list is present"
    row = payload["failures"][0]
    assert row["task"] == "deploy the service"
    assert "boom" in (row["error_excerpt"] or "")
    assert isinstance(row["modes"], list)
    assert all("mode_id" in m for m in row["modes"])
    assert "days" in payload, "the day rows ride along"


def test_the_filters_compose(tmp_path):
    now = time.time()
    _convo(tmp_path, "s", "today's failure", success=False,
           result=None, error="boom", created=now)
    _convo(tmp_path, "s", "old failure", success=False,
           result=None, error="boom", created=now - 30 * 86400)
    r = _run("--store", str(tmp_path / "s"), "recall-digest",
             "--since", "1w", "--json")
    payload = json.loads(r.stdout)
    assert [f["task"] for f in payload["failures"]] == \
        ["today's failure"]
    today = time.localtime()
    day = (f"{today.tm_year:04d}-{today.tm_mon:02d}-"
           f"{today.tm_mday:02d}")
    r2 = _run("--store", str(tmp_path / "s"), "recall-digest",
              "--day", day, "--json")
    payload2 = json.loads(r2.stdout)
    assert [f["task"] for f in payload2["failures"]] == \
        ["today's failure"], "the day filter threads the digest"


def test_the_fleet_view_threads_the_digest(tmp_path):
    _convo(tmp_path, "box-a", "box-a failure", success=False,
           result=None, error="boom a")
    _convo(tmp_path, "box-b", "box-b failure", success=False,
           result=None, error="boom b")
    r = _run("recall-digest", str(tmp_path / "box-a"),
             str(tmp_path / "box-b"))
    assert "{box-a}" in r.stdout and "{box-b}" in r.stdout, \
        "each failure names its store"


def test_the_mcp_tool_gains_digest(tmp_path):
    from approximately.mcp_server import _TOOLS, ServerContext, handle_request

    recall = next(t for t in _TOOLS if t["name"] == "recall")
    assert "digest" in recall["inputSchema"]["properties"], \
        "a client cannot discover a door the schema hides"
    _convo(tmp_path, "s", "deploy the service", success=False,
           result=None, error="boom")
    ctx = ServerContext(str(tmp_path / "s"))
    payload = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "recall",
                   "arguments": {"digest": True}},
    }, ctx)
    result = json.loads(payload["result"]["content"][0]["text"])
    assert result["failures"], "the wire carries the failures"
