"""v357: a symlink is not store evidence.

``snapshot`` walked the store with ``rglob`` and followed
symlinks — a link to anywhere on disk (or to ``/``) would pull
foreign bytes into the backup, or blow the archive up to the
whole disk. Links are skipped: the backup is evidence of THIS
store, not of wherever its links point.
"""

import tempfile
from pathlib import Path

from approximately.snapshot import _member_candidates
from approximately.store import TraceStore


def test_symlinks_are_skipped():
    store = TraceStore(tempfile.mkdtemp())
    real = store.directory / "real.json"
    real.write_text("{}", encoding="utf-8")
    outside = Path(tempfile.mkdtemp()) / "secret.json"
    outside.write_text('{"classified": true}', encoding="utf-8")
    (store.directory / "innocent.json").symlink_to(outside)
    names = {p.name for p in _member_candidates(store.directory)}
    assert "real.json" in names
    assert "innocent.json" not in names, \
        "the link is not evidence of this store"


def test_broken_symlinks_are_skipped_too():
    store = TraceStore(tempfile.mkdtemp())
    (store.directory / "dangling.json").symlink_to(
        Path(tempfile.mkdtemp()) / "gone.json")
    names = [p.name for p in _member_candidates(store.directory)]
    assert "dangling.json" not in names
