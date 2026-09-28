"""v147: safer store maintenance — clean previews, bulk rekey.

`clean --dry-run` counts what would be removed without touching a
file (retention policies get rehearsed before they run). `rotate
--all` re-keys every trace in one pass — the quarterly key-rotation
story — listing refusals and exiting 1 if any evidence was already
broken.
"""

import argparse
import json
import time

from approximately.cli import cmd_clean, cmd_rotate
from approximately.integrity import sign
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _aged_store(tmp_path, n_old=2, n_new=1):
    import os

    store = TraceStore(tmp_path / "s")
    ids_old, ids_new = [], []
    for i in range(n_old + n_new):
        rec = Recorder(f"run {i}", save=False)
        rec.respond("done", success=True)
        store.save(rec.trace)
        if i < n_old:
            # clean gates on file mtime; backdate it directly
            old = time.time() - 30 * 86400
            os.utime(store.directory / f"{rec.trace.id}.json",
                     (old, old))
            ids_old.append(rec.trace.id)
        else:
            ids_new.append(rec.trace.id)
    return store, ids_old, ids_new


def test_clean_dry_run_deletes_nothing(tmp_path):
    store, _ids_old, _ = _aged_store(tmp_path)
    before = {t.id for t in store.list_traces()}
    args = argparse.Namespace(store=str(store.directory),
                              keep_days=7, dry_run=True, json=True)
    assert cmd_clean(args) == 0
    after = {t.id for t in store.list_traces()}
    assert after == before and len(after) == 3


def test_clean_without_dry_run_removes(tmp_path):
    store, _ids_old, _ = _aged_store(tmp_path)
    args = argparse.Namespace(store=str(store.directory),
                              keep_days=7, dry_run=False, json=True)
    assert cmd_clean(args) == 0
    remaining = {t.id for t in store.list_traces()}
    assert len(remaining) == 1


def test_rotate_all_rekeys_every_signed_trace(tmp_path, capsys):

    key = b"k" * 8
    old_key = tmp_path / "old.key"
    old_key.write_bytes(key)
    store = TraceStore(tmp_path / "s")
    ids = []
    for i in range(3):
        rec = Recorder(f"signed {i}", save=False)
        rec.respond("done", success=True)
        sign(rec.trace, key=key)
        store.save(rec.trace)
        ids.append(rec.trace.id)
    new_key = tmp_path / "new.key"
    new_key.write_bytes(b"n" * 8)
    args = argparse.Namespace(store=str(store.directory),
                              trace=None,
                              old_key_file=str(old_key),
                              new_key_file=str(new_key), all=True,
                              json=True)
    assert cmd_rotate(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert sorted(payload["rotated"]) == sorted(ids)
    assert payload["refused"] == []


def test_rotate_all_lists_refusals(tmp_path, capsys):

    old_key = tmp_path / "old.key"
    old_key.write_bytes(b"k" * 8)
    store = TraceStore(tmp_path / "s")
    good = Recorder("good", save=False)
    good.respond("done", success=True)
    store.save(good.trace)
    bad = Recorder("tampered", save=False)
    bad.respond("done", success=True)
    sign(bad.trace, key=b"other-key" * 2)
    store.save(bad.trace)
    new_key = tmp_path / "new.key"
    new_key.write_bytes(b"n" * 8)
    args = argparse.Namespace(store=str(store.directory),
                              trace=None,
                              old_key_file=str(old_key),
                              new_key_file=str(new_key), all=True,
                              json=True)
    rc = cmd_rotate(args)
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["refused"]) == 1
    assert rc == 1
