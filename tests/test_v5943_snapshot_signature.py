"""v5943: the snapshot's manifest gets a signature.

The plain manifest's tamper-evidence is advisory: an attacker who
captures the archive can rebuild manifest and zip TOGETHER — every
hash recomputed, the de-coverage attack undetected. With a key
(``snapshot --key-file``) the manifest is also HMAC-signed, and
``restore --check --key-file`` audits both directions (the
evidence packs' precedent): a signed snapshot under a keyless
reviewer is LOCKED — saying trusted would let the attack win by
omission; an unsigned snapshot under a key-holding reviewer is
advisory and named; the wrong key blesses nothing. ``restore``
carries the same verdict into extraction, and the MCP snapshot
tool takes ``key_file`` across all three ops.
"""

import json
import zipfile
from pathlib import Path

import pytest

from approximately.recorder import Recorder
from approximately.snapshot import restore, snapshot, verify_snapshot
from approximately.store import TraceStore

KEY = b"night-shift-secret"
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def store(tmp_path):
    store = TraceStore(tmp_path / "s")
    rec = Recorder("signed snap target", save=False)
    rec.tool("deploy", {}, result=None, error="boom")
    rec.respond("done", success=False)
    store.save(rec.trace)
    return store


def test_a_signed_snapshot_verifies_with_its_key(store, tmp_path):
    out = tmp_path / "signed.zip"
    snapshot(store.directory, out, key=KEY)
    manifest = json.loads(
        zipfile.ZipFile(out).read("manifest.json"))
    assert manifest.get("signature"), "the signed manifest carries it"
    result, offenders = verify_snapshot(out, key=KEY)
    assert offenders == [] and result["members"]
    assert restore(out, tmp_path / "r1", key=KEY)["members"] >= 1, \
        "the right key restores"


def test_a_signed_snapshot_without_the_key_is_locked(store, tmp_path):
    out = tmp_path / "signed.zip"
    snapshot(store.directory, out, key=KEY)
    _, offenders = verify_snapshot(out)
    assert offenders and "no key to verify" in offenders[0], (
        "saying trusted would let the de-coverage attack win by "
        "omission")
    with pytest.raises(ValueError, match="verification failed"):
        restore(out, tmp_path / "r2")
    wrong = verify_snapshot(out, key=b"wrong-key")
    assert any("HMAC mismatch" in o for o in wrong[1]), \
        "the wrong key blesses nothing"


def test_an_unsigned_snapshot_under_a_key_is_advisory(store, tmp_path):
    out = tmp_path / "plain.zip"
    snapshot(store.directory, out)
    _plain, plain_offenders = verify_snapshot(out)
    assert plain_offenders == [], \
        "without a key on either side, today's behavior stands"
    signed_check = verify_snapshot(out, key=KEY)
    assert any("not signed" in o for o in signed_check[1]), (
        "a key-holding reviewer is told the archive cannot be "
        "authenticated")


def test_the_doors_take_the_key_end_to_end(store, tmp_path):
    import subprocess
    import sys

    def run(*args):
        return subprocess.run(
            [sys.executable, "-m", "approximately", *args],
            capture_output=True, text=True, cwd=ROOT,
            encoding="utf-8")

    key = tmp_path / "team.key"
    key.write_text("night-shift-secret", encoding="utf-8")
    signed = tmp_path / "signed.zip"
    r = run("--store", str(store.directory), "snapshot",
            str(signed), "--key-file", str(key))
    assert r.returncode == 0, r.stderr
    r = run("restore", str(signed), "--check", "--key-file",
            str(key))
    assert r.returncode == 0 and "every hash matches" in r.stdout
    r = run("restore", str(signed), "--check")
    assert r.returncode == 1 and "no key to verify" in r.stdout


def test_the_mcp_tool_takes_the_key(tmp_path):
    from approximately.mcp_server import _TOOLS, ServerContext, handle_request

    snap = next(t for t in _TOOLS if t["name"] == "snapshot")
    assert "key_file" in snap["inputSchema"]["properties"]
    ctx = ServerContext(str(tmp_path / "s"))
    signed = tmp_path / "signed.zip"
    handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "snapshot",
                   "arguments": {"path": str(signed)}},
    }, ctx)
    payload = handle_request({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "snapshot",
                   "arguments": {"op": "check", "path": str(signed),
                                 "key_file": "missing-file.pem"}},
    }, ctx)
    # a missing key file is a named refusal, not a silent downgrade
    result = json.loads(payload["result"]["content"][0]["text"])
    assert payload["result"]["isError"] or \
        result.get("intact") is False or result.get("mismatches"), \
        "a key file that does not exist must not bless the audit"
