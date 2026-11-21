"""v5937: audit an archive where it lies — extract nothing.

``restore --check SNAP.zip`` recomputes every member hash against
the manifest and reports: an intact archive answers 0, a tampered
one answers 1 NAMING the members that drifted (a missing member,
a sha256 mismatch, an unmanifested stowaway), and an unreadable
one answers 2. The door exists because restore already verified —
but only on its way to extracting somewhere: auditing the backup
you are ABOUT to trust, or the one that has been sitting on a
shelf, should not require a target directory. ``--check`` with
``--into`` is refused by name (check extracts nothing), and the
MCP snapshot tool gains the ``check`` op with the same verdict.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "approximately", *args],
        capture_output=True, text=True, cwd=str(ROOT),
        encoding="utf-8")


def _archive(tmp_path):
    from approximately.recorder import Recorder
    from approximately.snapshot import snapshot
    from approximately.store import TraceStore

    store = TraceStore(tmp_path / "s")
    rec = Recorder("check me", model="m/1", store=store, save=False)
    rec.tool("deploy", {}, result="ok")
    rec.respond("done", success=True)
    store.save(rec.trace)
    out = tmp_path / "snap.zip"
    report = snapshot(store.directory, out)
    return out, report


def test_an_intact_archive_answers_zero(tmp_path):
    out, _ = _archive(tmp_path)
    r = _run("restore", str(out), "--check")
    assert r.returncode == 0, r.stderr
    assert "member(s)" in r.stdout
    assert "every hash matches the manifest" in r.stdout
    assert not (tmp_path / "restored").exists(), \
        "check extracts nothing, anywhere"
    r = _run("restore", str(out), "--check", "--json")
    payload = json.loads(r.stdout)
    assert payload["intact"] is True and payload["members"] >= 1
    assert payload["mismatches"] == []


def test_a_tampered_archive_answers_one_and_names_the_member(
        tmp_path):
    out, _ = _archive(tmp_path)
    import zipfile as zf

    with zf.ZipFile(out) as archive:
        names = [n for n in archive.namelist()
                 if n.endswith(".json") and "manifest" not in n]
        victim = names[0]
        contents = {n: archive.read(n)
                    for n in archive.namelist()}
    contents[victim] += b" tampered"
    with zf.ZipFile(out, "w", zf.ZIP_DEFLATED) as z:
        for name, data in contents.items():
            z.writestr(name, data)
    r = _run("restore", str(out), "--check")
    assert r.returncode == 1, \
        "a tampered archive is a verdict, not an error"
    assert "mismatch" in r.stdout
    r = _run("restore", str(out), "--check", "--json")
    payload = json.loads(r.stdout)
    assert payload["intact"] is False
    assert payload["mismatches"], "the drifted member is named"
    # a real restore still refuses the same archive, unchanged
    r = _run("restore", str(out), "--into", str(tmp_path / "r"))
    assert r.returncode == 2, "restore keeps its own refusal"


def test_an_unreadable_archive_answers_two(tmp_path):
    missing = _run("restore", str(tmp_path / "nope.zip"), "--check")
    assert missing.returncode == 2
    assert "no such snapshot" in missing.stderr
    torn = tmp_path / "torn.zip"
    torn.write_bytes(b"PK\x03\x04 not really a zip")
    r = _run("restore", str(torn), "--check")
    assert r.returncode == 2 and "Traceback" not in r.stderr


def test_check_with_into_is_refused_by_name(tmp_path):
    out, _ = _archive(tmp_path)
    r = _run("restore", str(out), "--check",
             "--into", str(tmp_path / "elsewhere"))
    assert r.returncode == 2
    assert "--check extracts nothing" in r.stderr
    r = _run("restore", str(out))
    assert r.returncode == 2 and "--into" in r.stderr, \
        "plain restore still needs its target"


def test_the_mcp_tool_gains_the_check_op(tmp_path):
    from approximately.mcp_server import _TOOLS, ServerContext, handle_request

    snap = next(t for t in _TOOLS if t["name"] == "snapshot")
    ops = snap["inputSchema"]["properties"]["op"]["enum"]
    assert "check" in ops, \
        "a client cannot discover a door the schema hides"
    out, _ = _archive(tmp_path)
    ctx = ServerContext(str(tmp_path / "s"))
    payload = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "snapshot",
                   "arguments": {"op": "check", "path": str(out)}},
    }, ctx)
    result = json.loads(payload["result"]["content"][0]["text"])
    assert result["intact"] is True and result["members"] >= 1
