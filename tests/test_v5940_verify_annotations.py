"""v5940: the annotation chain gets a first-class door.

``doctor --deep`` walks the annotation chain, but deep is the
whole house sweep — a cron (or an agent's pre-flight) that wants
only the triage-log verdict should not pay for every record's
chain recomputation. ``verify --annotations`` is that door: one
store or a fleet (a section per store, the exit the worst; --json
is one array), exit 1 names the broken links, and the counts stay
honest about what the door can know — legacy unsigned lines and
rotated-key entries are counted, never guessed at. ``--key-file``
feeds keyed entries; ``--all`` and a bare trace id are refused by
name.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "approximately", *args],
        capture_output=True, text=True, cwd=str(ROOT),
        encoding="utf-8")


def _seed(tmp_path):
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    stores = []
    for name in ("a", "b"):
        store = TraceStore(tmp_path / name)
        rec = Recorder("verify ann target", save=False)
        rec.tool("deploy", {}, result="ok")
        rec.respond("done", success=False)
        store.save(rec.trace)
        store.annotate(rec.trace.id, "note one",
                       verdict="confirmed")
        stores.append((store, rec.trace.id))
    return stores


def test_one_store_verdicts_intact(tmp_path):
    _seed(tmp_path)
    r = _run("verify", "--annotations", "--store",
             str(tmp_path / "a"))
    assert r.returncode == 0, r.stderr
    assert "1 signed" in r.stdout and "chain intact" in r.stdout
    r = _run("verify", "--annotations", "--store",
             str(tmp_path / "a"), "--json")
    payload = json.loads(r.stdout)
    assert payload["intact"] is True and payload["signed"] == 1


def test_the_fleet_sections_and_the_worst_exit(tmp_path):
    _seed(tmp_path)
    r = _run("verify", "--annotations",
             str(tmp_path / "a"), str(tmp_path / "b"), "--json")
    assert r.returncode == 0, r.stdout
    payload = json.loads(r.stdout)
    assert isinstance(payload, list) and len(payload) == 2, \
        "one array, not one document per box"
    path = tmp_path / "b" / "annotations.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[0])
    entry["verdict"] = "false-positive"
    lines[0] = json.dumps(entry)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    r = _run("verify", "--annotations",
             str(tmp_path / "a"), str(tmp_path / "b"))
    assert r.returncode == 1, \
        "the fleet exit is the worst of its sections"
    assert "== b ==" in r.stdout and "BROKEN" in r.stdout
    assert "== a ==" in r.stdout, \
        "the clean box's verdict still renders in its section"


def test_refusals_come_by_name(tmp_path):
    _seed(tmp_path)
    r = _run("verify", "--annotations", "--all",
             "--store", str(tmp_path / "a"))
    assert r.returncode == 2 and "drop --all" in r.stderr
    r = _run("verify", "someid", "--annotations",
             "--store", str(tmp_path / "a"))
    assert r.returncode == 2 and "drop the trace id" in r.stderr


def test_a_key_file_feeds_keyed_entries(tmp_path):
    store, tid = _seed(tmp_path)[0]
    key = tmp_path / "team.key"
    key.write_text("team-secret", encoding="utf-8")
    os.environ["APPROXIMATELY_SIGNING_KEY"] = "team-secret"
    store.annotate(tid, "keyed entry", verdict="confirmed")
    os.environ.pop("APPROXIMATELY_SIGNING_KEY")
    r = _run("verify", "--annotations", "--store",
             str(store.directory))
    assert r.returncode == 0 and "unverifiable" in r.stdout, \
        "a rotated key is unverifiable, never tampered"
    r = _run("verify", "--annotations", "--store",
             str(store.directory), "--key-file", str(key))
    assert r.returncode == 0 and "unverifiable" not in r.stdout, \
        "the named key file completes the content check"


def test_the_mcp_tool_gains_annotations(tmp_path):
    from approximately.mcp_server import _TOOLS, ServerContext, handle_request

    verify = next(t for t in _TOOLS if t["name"] == "verify")
    props = verify["inputSchema"]["properties"]
    assert "annotations" in props, \
        "a client cannot discover a door the schema hides"
    _seed(tmp_path)
    ctx = ServerContext(str(tmp_path / "a"))
    payload = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "verify",
                   "arguments": {"annotations": True}},
    }, ctx)
    result = json.loads(payload["result"]["content"][0]["text"])
    assert result["intact"] is True and result["signed"] == 1
    path = tmp_path / "a" / "annotations.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[0])
    entry["note"] = "quietly different"
    lines[0] = json.dumps(entry)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    payload = handle_request({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "verify",
                   "arguments": {"annotations": True}},
    }, ctx)
    result = json.loads(payload["result"]["content"][0]["text"])
    assert result["intact"] is False and result["broken"]
