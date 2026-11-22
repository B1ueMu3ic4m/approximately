"""v5942: the diary closes the loop, and the annotate door takes
the key.

v5941 put each conversation's verdict on its diary line; this
round closes the artifact with the number a reader can ACT on: a
``## Triage`` tally — how many failed conversations carry a
verdict, which words, how many still unannotated (a day with no
failures closes silently). And ``annotate --key-file`` completes
the chain story's parity: a keyed stamp from a named file (the
CLI, the store API, and the MCP tool), verified by the same file
through ``verify --annotations``.
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

    store = TraceStore(tmp_path / "s")
    for task, ok in (("failed run one", False),
                     ("failed run two", False),
                     ("failed run three", False),
                     ("ok run", True)):
        rec = Recorder(task, save=False)
        rec.tool("deploy", {}, result="ok")
        rec.respond("done", success=ok)
        store.save(rec.trace)
    ids = {t.task: t.id for t in store.list_traces()}
    store.annotate(ids["failed run one"], "first look",
                   verdict="confirmed")
    store.annotate(ids["failed run two"], "dismissed",
                   verdict="false-positive")
    return store, ids


def test_the_diary_closes_with_the_tally(tmp_path):
    store, _ = _seed(tmp_path)
    out = tmp_path / "diary.md"
    r = _run("--store", str(store.directory), "recall", "--export",
             str(out))
    assert r.returncode == 0, r.stderr
    text = out.read_text(encoding="utf-8")
    assert "## Triage" in text
    assert "2 of 3 failed conversation(s) carry a verdict" in text
    assert "1 confirmed · 1 false-positive" in text
    assert "1 still unannotated" in text


def test_a_failure_free_day_closes_silently(tmp_path):
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    store = TraceStore(tmp_path / "s2")
    rec = Recorder("all fine", save=False)
    rec.tool("ls", {}, result="ok")
    rec.respond("done", success=True)
    store.save(rec.trace)
    out = tmp_path / "d2.md"
    r = _run("--store", str(store.directory), "recall", "--export",
             str(out))
    assert r.returncode == 0, r.stderr
    assert "## Triage" not in out.read_text(encoding="utf-8")


def test_annotate_takes_a_key_file(tmp_path):
    store, ids = _seed(tmp_path)
    key = tmp_path / "shift.key"
    key.write_text("shift-secret", encoding="utf-8")
    env = dict(os.environ)
    os.environ.pop("APPROXIMATELY_SIGNING_KEY", None)
    r = _run("--store", str(store.directory), "annotate",
             ids["failed run three"], "keyed look",
             "--verdict", "confirmed", "--key-file", str(key))
    assert r.returncode == 0, r.stderr
    entry = json.loads(
        (store.directory / "annotations.jsonl")
        .read_text(encoding="utf-8").splitlines()[-1])
    assert entry["alg"] == "hmac-sha256-chain-v2"
    # without any key in the environment: earlier entries verify,
    # the keyed one is unverifiable — never tampered
    r = _run("--store", str(store.directory), "verify",
             "--annotations")
    assert r.returncode == 0 and "1 unverifiable" in r.stdout, \
        r.stdout
    # the named key completes the check
    r = _run("--store", str(store.directory), "verify",
             "--annotations", "--key-file", str(key))
    assert r.returncode == 0 and "chain intact" in r.stdout
    os.environ.clear()
    os.environ.update(env)


def test_the_mcp_annotate_takes_the_key(tmp_path):
    from approximately.mcp_server import _TOOLS, ServerContext, handle_request

    annotate = next(t for t in _TOOLS if t["name"] == "annotate")
    assert "key_file" in annotate["inputSchema"]["properties"]
    store, ids = _seed(tmp_path)
    key = tmp_path / "shift.key"
    key.write_text("shift-secret", encoding="utf-8")
    ctx = ServerContext(str(store.directory))
    payload = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "annotate",
                   "arguments": {"trace": ids["failed run three"],
                                 "note": "keyed via wire",
                                 "verdict": "confirmed",
                                 "key_file": str(key)}},
    }, ctx)
    result = json.loads(payload["result"]["content"][0]["text"])
    assert result["annotated"] is True
    entry = result["entry"]
    assert entry["alg"] == "hmac-sha256-chain-v2"
