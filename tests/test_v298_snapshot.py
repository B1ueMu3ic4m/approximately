"""v298: snapshot & restore — lossless store backup, tamper-evident.

``evidence --all`` curates per-trace packs; a snapshot moves the
whole store. The manifest rides inside the zip and restore recomputes
every hash before extracting. And the roundtrip caught a real bug:
``list_traces`` globbed every root ``*.json``, so the price catalog
parsed as a degenerate empty-task trace and polluted every fleet
surface — the trace_files() helper now gates every trace-facing glob.
"""

import json

import pytest

from approximately.mcp_server import ServerContext, _tool_snapshot
from approximately.prices import set_rate
from approximately.snapshot import restore, snapshot, verify_snapshot
from approximately.store import TraceStore, trace_files
from approximately.trace import Step, Trace


def _seed(src):
    store = TraceStore(src)
    last = None
    for i in range(3):
        t = Trace(task=f"run {i}", model="m")
        t.add(Step(kind="tool_call", tool="sh", result="ok",
                   tokens=10))
        t.success = True
        store.save(t)
        last = t
    store.annotate(last.id, "note", verdict="confirmed")
    set_rate(src, "gpt-x", 0.5)
    qdir = src / ".quarantine"
    qdir.mkdir(exist_ok=True)
    (qdir / "poison.json").write_text("{bad", encoding="utf-8")
    return store, last


def test_snapshot_roundtrip(tmp_path):
    src = tmp_path / "store"
    _, last = _seed(src)
    out = tmp_path / "snap.zip"
    rep = snapshot(src, out)
    assert rep["members"] == 6  # 3 traces + annotations + catalog + quarantine
    assert out.is_file()
    into = tmp_path / "restored"
    r = restore(out, into)
    assert r["members"] == 6
    store2 = TraceStore(into)
    assert len(store2.list_traces()) == 3  # furniture is not a trace
    assert store2.annotations(last.id)[0]["note"] == "note"
    from approximately.prices import load_catalog

    assert load_catalog(into) == {"gpt-x": 0.5}
    assert (into / ".quarantine" / "poison.json").read_text() == "{bad"
    manifest, offenders = verify_snapshot(out)
    assert offenders == []
    assert manifest["format"] == 1


def test_list_traces_skips_furniture(tmp_path):
    src = tmp_path / "store"
    _seed(src)
    store = TraceStore(src)
    ids = [t.id for t in store.list_traces()]
    assert len(ids) == 3
    assert all(len(i) == 12 for i in ids)  # no 'prices' stem
    names = [p.name for p in trace_files(src)]
    assert "prices.json" not in names
    assert sum(1 for p in trace_files(src)) == 3


def test_tampered_archive_refuses(tmp_path):
    import zipfile

    src = tmp_path / "store"
    _seed(src)
    out = tmp_path / "snap.zip"
    snapshot(src, out)
    with zipfile.ZipFile(out) as zf:
        members = {n: zf.read(n) for n in zf.namelist()
                   if n != "manifest.json"}
        manifest = zf.read("manifest.json")
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        for name, data in members.items():
            payload = data + (b"tampered\n"
                              if name.endswith("annotations.jsonl")
                              else b"")
            zf.writestr(name, payload)
        zf.writestr("manifest.json", manifest)
    _, offenders = verify_snapshot(bad)
    assert any("mismatch" in o for o in offenders)
    with pytest.raises(ValueError, match="verification failed"):
        restore(bad, tmp_path / "x")


def test_member_removed_and_extra_member_refuse(tmp_path):
    import zipfile

    src = tmp_path / "store"
    _seed(src)
    out = tmp_path / "snap.zip"
    snapshot(src, out)
    with zipfile.ZipFile(out) as zf:
        members = {n: zf.read(n) for n in zf.namelist()
                   if n != "manifest.json"
                   and not n.endswith("annotations.jsonl")}
        manifest = zf.read("manifest.json")
    missing = tmp_path / "missing.zip"
    with zipfile.ZipFile(missing, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
        zf.writestr("manifest.json", manifest)
    _, offenders = verify_snapshot(missing)
    assert any("missing from archive" in o for o in offenders)
    extra = tmp_path / "extra.zip"
    with zipfile.ZipFile(extra, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
        zf.writestr("injected.json", "{}")
        zf.writestr("manifest.json", manifest)
    _, offenders = verify_snapshot(extra)
    assert any("not in manifest" in o for o in offenders)


def test_clash_refusal_and_force(tmp_path):
    src = tmp_path / "store"
    _seed(src)
    out = tmp_path / "snap.zip"
    snapshot(src, out)
    into = tmp_path / "restored"
    restore(out, into)
    with pytest.raises(ValueError, match="already exist"):
        restore(out, into)
    r = restore(out, into, force=True)
    assert r["members"] == 6


def test_not_a_snapshot_and_missing(tmp_path):
    notzip = tmp_path / "plain.zip"
    import zipfile

    with zipfile.ZipFile(notzip, "w") as zf:
        zf.writestr("random.txt", "hello")
    with pytest.raises(ValueError, match="not a snapshot"):
        verify_snapshot(notzip)
    with pytest.raises(ValueError, match="no such snapshot"):
        verify_snapshot(tmp_path / "ghost.zip")


def test_cli_snapshot_restore(tmp_path, capsys):
    from approximately.cli import cmd_restore, cmd_snapshot

    src = tmp_path / "store"
    _seed(src)
    out = tmp_path / "snap.zip"
    args = argparse_ns(store=str(src), snapshot=str(out),
                       **{"json": False})
    assert cmd_snapshot(args) == 0
    assert "6 members" in capsys.readouterr().out
    rargs = argparse_ns(snapshot=str(out), into=str(tmp_path / "r"),
                        force=False, **{"json": False})
    assert cmd_restore(rargs) == 0
    assert "restored 6 members" in capsys.readouterr().out
    # refusal path
    bad = argparse_ns(snapshot=str(tmp_path / "ghost.zip"),
                      into=str(tmp_path / "r2"), force=False,
                      **{"json": False})
    assert cmd_restore(bad) == 2
    capsys.readouterr()


def argparse_ns(**kw):
    import argparse

    return argparse.Namespace(**kw)


def test_mcp_snapshot(tmp_path):
    src = tmp_path / "store"
    _seed(src)
    ctx = ServerContext(str(src))
    out = str(tmp_path / "snap.zip")
    rep = _tool_snapshot(ctx, {"path": out})
    assert rep["members"] == 6
    with pytest.raises(KeyError, match="needs the archive"):
        _tool_snapshot(ctx, {})
    with pytest.raises(KeyError, match="needs into"):
        _tool_snapshot(ctx, {"op": "restore", "path": out})
    r = _tool_snapshot(ctx, {"op": "restore", "path": out,
                             "into": str(tmp_path / "r")})
    assert r["members"] == 6
    try:
        _tool_snapshot(ctx, {"op": "restore", "path": out,
                             "into": str(tmp_path / "r")})
        raise AssertionError("should refuse")
    except KeyError as exc:
        assert "already exist" in str(exc)
    forced = _tool_snapshot(ctx, {"op": "restore", "path": out,
                                  "into": str(tmp_path / "r"),
                                  "force": True})
    assert forced["members"] == 6


def test_json_payloads(tmp_path):
    import argparse
    import contextlib
    import io

    from approximately.cli import cmd_restore, cmd_snapshot

    src = tmp_path / "store"
    _seed(src)
    out = tmp_path / "snap.zip"
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert cmd_snapshot(argparse.Namespace(
            store=str(src), snapshot=str(out), **{"json": True})) == 0
    payload = json.loads(buf.getvalue())
    assert payload["members"] == 6
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert cmd_restore(argparse.Namespace(
            snapshot=str(out), into=str(tmp_path / "r"),
            force=False, **{"json": True})) == 0
    payload = json.loads(buf.getvalue())
    assert payload["restored_into"].endswith("r")
