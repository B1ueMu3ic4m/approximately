"""v349: a snapshot member must not aim the extraction.

``restore`` extracted members by name — and a doctored archive
whose manifest hashes match its own forged members could name a
member ``../../evil.txt``: the hash check passes (the manifest is
the attacker's), and the file lands outside the restore target.
The restore now refuses any member that resolves outside the
target before a single byte is written. Legitimate archives never
contain such names — snapshot only writes store-relative paths.
"""

import hashlib
import json
import tempfile
import zipfile
from pathlib import Path

import pytest

from approximately.snapshot import restore


def _forged(members):
    tmp = Path(tempfile.mkdtemp())
    zpath = tmp / "evil.zip"
    manifest = {"created_at": 0.0, "format": 1, "store": str(tmp),
                "members": {n: hashlib.sha256(d).hexdigest()
                            for n, d in members.items()}}
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        for name, data in members.items():
            zf.writestr(name, data)
    return zpath


def test_dotdot_member_is_refused_before_any_write():
    zpath = _forged({"../../evil.txt": b"pwned"})
    into = Path(tempfile.mkdtemp()) / "restored"
    with pytest.raises(ValueError, match="escape"):
        restore(zpath, into)
    assert not (into.resolve().parent.parent / "evil.txt").exists(), \
        "not one byte outside the target"
    assert not into.exists(), "the refusal precedes any mkdir"


def test_absolute_member_is_refused_too():
    outside = Path(tempfile.mkdtemp()) / "evil.txt"
    zpath = _forged({str(outside): b"pwned"})
    into = Path(tempfile.mkdtemp()) / "restored"
    with pytest.raises(ValueError, match="escape"):
        restore(zpath, into)
    assert not outside.exists()


def test_legitimate_nested_members_still_restore():
    from approximately.recorder import Recorder
    from approximately.snapshot import snapshot
    from approximately.store import TraceStore

    store = TraceStore(tempfile.mkdtemp())
    rec = Recorder("kept run", store=store)
    rec.tool("sh", {}, result="ok")
    rec.respond("done", success=True)
    store.save(rec.trace)
    snap = Path(tempfile.mkdtemp()) / "snap.zip"
    snapshot(store.directory, snap)
    into = Path(tempfile.mkdtemp()) / "restored"
    report = restore(snap, into)
    assert report["members"] >= 1
    assert any(into.rglob("*.json")), "the store came back intact"
