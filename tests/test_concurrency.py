"""Concurrent-store safety: atomic writes and same-id serialization."""

from __future__ import annotations

import json
import threading

from approximately.recorder import Recorder


def _make_trace(task, marker):
    with Recorder(task, save=False) as rec:
        rec.tool("probe", {"marker": marker}, result=marker)
        rec.respond(f"done {marker}", success=True)
    return rec.trace


def test_save_is_atomic_reader_never_sees_partial(store, failing_trace):
    """A reader polling during repeated saves only ever sees valid JSON."""
    store.save(failing_trace)
    observed: list = []
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            raw = (store.directory / f"{failing_trace.id}.json")
            if raw.exists():
                try:
                    json.loads(raw.read_text(encoding="utf-8"))
                    observed.append("ok")
                except json.JSONDecodeError:
                    observed.append("PARTIAL")

    thread = threading.Thread(target=reader)
    thread.start()
    for i in range(30):
        failing_trace.meta["iteration"] = i
        store.save(failing_trace)
    stop.set()
    thread.join()
    assert observed and "PARTIAL" not in observed


def test_concurrent_saves_same_id_produce_valid_final_state(store):
    trace_a = _make_trace("writer a", "A")
    trace_b = _make_trace("writer b", "B")
    trace_b.id = trace_a.id  # same id, different content

    threads = [threading.Thread(target=store.save, args=(t,))
               for t in (trace_a, trace_b)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    loaded = store.load(trace_a.id)
    assert loaded is not None
    # the final file is one of the two complete writes, never a blend
    markers = [s.result for s in loaded.steps if s.result in ("A", "B")]
    assert markers and len(set(markers)) == 1


def test_no_stale_lock_files_after_save(store, failing_trace):
    store.save(failing_trace)
    locks = list(store.directory.glob(".*.lock"))
    assert locks == []


def test_stale_lock_is_broken_and_save_succeeds(store, failing_trace):
    """A crashed writer leaves a lock; the next save breaks it (after the
    bounded timeout shortened here via many pre-created locks is not
    needed — we simulate by pre-creating and shrinking the deadline via
    monkeypatched time)."""
    import time as _time

    from approximately import store as store_module

    store.save(failing_trace)  # ensure dir + base file
    lock = store.directory / f".{failing_trace.id}.lock"
    lock.write_bytes(b"")  # simulate a crashed writer

    real_time = _time.time
    # first time.time() call (deadline) is 'now'; the loop check sees a
    # time far in the future so the stale branch fires immediately
    calls = {"n": 0}

    def fake_time():
        calls["n"] += 1
        return real_time() + (0 if calls["n"] == 1 else 3600)

    original = store_module.time.time
    store_module.time.time = fake_time
    try:
        saved = store.save(failing_trace)
    finally:
        store_module.time.time = original
    assert saved.exists()
    assert not lock.exists()  # stale lock removed after recovery
    assert store.load(failing_trace.id) is not None


def test_concurrent_readers_during_lock_waits(store, failing_trace):
    """A second save while the lock is held waits, then succeeds."""
    import threading
    import time as _time

    store.save(failing_trace)
    lock = store.directory / f".{failing_trace.id}.lock"
    lock.write_bytes(b"")
    release = threading.Event()

    def hold_then_release():
        release.wait(timeout=2)
        lock.unlink(missing_ok=True)

    thread = threading.Thread(target=hold_then_release)
    thread.start()
    results = []

    def saver():
        results.append(store.save(failing_trace))

    saver_thread = threading.Thread(target=saver)
    saver_thread.start()
    _time.sleep(0.05)  # let the saver hit the lock
    release.set()
    thread.join()
    saver_thread.join()
    assert results and results[0].exists()
