"""v407: one flush at a time.

Two `--flush` processes rewriting the queue in parallel would
clobber each other: both read the same rows, both post (the
receiver dedups on import, so evidence stays safe), and then
BOTH rewrite the file — the loser's kept rows and attempt
counts vanish, and a forever-failing shipment forgets it has
been failing. The read-modify-write holds the spool's
exclusive lock now: O_EXCL create, zero dependencies, Windows
included; a lock older than five minutes is a crashed flush's
leftover and is taken over; a live lock refuses by name. Plans
(dry runs) never lock — reading is not deciding, and it is
also not contention.
"""

import tempfile
import time

import pytest

from approximately import cli
from approximately.cli import _acquire_lock, _release_lock, _spool_append, _spool_flush
from approximately.recorder import Recorder
from approximately.store import TraceStore

KEY = b"lock-key"


def _store_with_spool(n=1):
    store = TraceStore(tempfile.mkdtemp())
    rec = Recorder("lock task", store=store)
    rec.tool("sh", {"cmd": "x"}, result="ok")
    rec.respond("done", success=True)
    store.save(rec.trace)
    spool = cli._spool_path(str(store.directory))
    for _ in range(n):
        _spool_append(spool, rec.trace.id,
                      "http://127.0.0.1:1/", "box-a")
    return store, spool


def test_a_second_flush_refuses_while_one_holds_the_lock():
    store, spool = _store_with_spool()
    lock = spool.with_name(spool.name + ".lock")
    _acquire_lock(lock)
    with pytest.raises(ValueError, match="spool is locked"):
        _spool_flush(store, spool, KEY)
    _release_lock(lock)
    report = _spool_flush(store, spool, KEY)
    assert report["kept"] == 1, \
        "the refusal was clean - the queue is untouched"


def test_a_stale_lock_is_taken_over():
    store, spool = _store_with_spool()
    lock = spool.with_name(spool.name + ".lock")
    _acquire_lock(lock)
    old = time.time() - 400.0
    import os

    os.utime(lock, (old, old))
    report = _spool_flush(store, spool, KEY)
    assert report["kept"] == 1, \
        "a crashed flush's leftover does not block forever"
    assert not lock.exists(), "the new flush owns the lock"


def test_the_lock_is_released_on_success_and_on_error():
    store, spool = _store_with_spool(1)
    lock = spool.with_name(spool.name + ".lock")
    _spool_flush(store, spool, KEY)
    assert not lock.exists(), "released after the flush"
    # an error inside the locked section still releases
    real = cli._spool_rows

    def boom(path):
        real(path)
        raise RuntimeError("mid-flush explosion")

    cli._spool_rows = boom
    try:
        with pytest.raises(RuntimeError):
            _spool_flush(store, spool, KEY)
    finally:
        cli._spool_rows = real
    assert not lock.exists(), \
        "released even when the flush explodes mid-flight"


def test_a_dry_run_never_locks():
    store, spool = _store_with_spool()
    lock = spool.with_name(spool.name + ".lock")
    _acquire_lock(lock)
    plan = _spool_flush(store, spool, KEY, dry_run=True)
    assert plan["dry_run"] is True and plan["kept"] == 1, \
        "reading is not deciding - and not contention either"
    _release_lock(lock)


def test_the_lock_names_its_holder():
    _store, spool = _store_with_spool()
    lock = spool.with_name(spool.name + ".lock")
    _acquire_lock(lock)
    import os

    assert lock.read_text().strip() == str(os.getpid())
    _release_lock(lock)
