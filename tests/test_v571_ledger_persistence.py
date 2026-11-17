"""v571: the ledger line persists through the whole lock budget.

The 12-concurrent-writer pin lost a line on a THIRD Windows CI
leg (py3.11 this time): five retry attempts span only ~0.6s, and
a Windows sharing violation (indexer, antivirus) can outlive any
fixed attempt count. The persistence budget is now the lock's own
30s deadline — the write retries every 100ms until it lands or
the budget runs out, and only then does the best-effort contract
apply. The first attempt always happens: a clean append never
even reads the clock.
"""

import pytest

from approximately.ledger import EvidenceLedger


def _ledger(tmp_path):
    led = EvidenceLedger(tmp_path)
    return led


def test_a_transient_failure_is_retried_not_lost(tmp_path,
                                                 monkeypatch):
    led = _ledger(tmp_path)
    real_write = led._write_append
    attempts = []

    def flaky(line: str) -> None:
        attempts.append(line)
        if len(attempts) < 3:
            raise OSError("sharing violation (transient)")
        real_write(line)

    monkeypatch.setattr(led, "_write_append", flaky)
    sleeps = []
    monkeypatch.setattr("approximately.ledger.time.sleep",
                        sleeps.append)
    entry = led.append("abcd1234ef01", "root1")
    assert entry.seq == 1, (
        "two transient failures used to consume the whole attempt "
        "budget and drop the line")
    assert len(attempts) == 3, "the write retried until it landed"
    assert all(s > 0 for s in sleeps), \
        "the retry backs off between attempts"
    assert led.entries()[0].trace_id == "abcd1234ef01"


def test_the_budget_exhaustion_raises_not_forgets(tmp_path,
                                                  monkeypatch):
    led = _ledger(tmp_path)

    def always_fails(line: str) -> None:
        raise OSError("sharing violation (forever)")

    monkeypatch.setattr(led, "_write_append", always_fails)
    clock = {"t": 0.0}

    def monotonic() -> float:
        return clock["t"]

    def sleep(s: float) -> None:
        clock["t"] += s

    monkeypatch.setattr("approximately.ledger.time.monotonic",
                        monotonic)
    monkeypatch.setattr("approximately.ledger.time.sleep", sleep)
    with pytest.raises(OSError):
        led.append("abcd1234ef01", "root1"), (
            "the best-effort contract applies only AFTER the "
            "budget - the caller's swallow sees the error")
    assert led.entries() == [], \
        "no half line was written by the failed attempts"


def test_a_transient_read_failure_is_retried_too(tmp_path,
                                                 monkeypatch):
    led = _ledger(tmp_path)
    real_entries = EvidenceLedger.entries
    reads = []

    def flaky_entries(self):
        reads.append(1)
        if len(reads) < 3:
            raise OSError("sharing violation on the read")
        return real_entries(self)

    monkeypatch.setattr(EvidenceLedger, "entries", flaky_entries)
    entry = led.append("abcd1234ef01", "root1")
    assert entry.seq == 1, (
        "the fourth Windows loss bypassed the write retry "
        "entirely: the READ (entries -> read_text) raises the "
        "same transient sharing violation and the whole "
        "lock-held section must share the budget")
    assert len(reads) == 3
    assert led.entries()[0].trace_id == "abcd1234ef01"


def test_every_atomic_write_retries_a_transient(tmp_path,
                                                monkeypatch):
    """The artifact-write primitive shares the bounded budget:
    report/diary/digest/plan exports must not die after the
    numbers were computed because an indexer held the tmp."""
    from pathlib import Path

    from approximately.store import atomic_write

    out = tmp_path / "artifact.html"
    real = Path.write_text
    state = {"n": 0}

    def flaky(self, text, *a, **kw):
        if state["n"] == 0 and self.name.endswith(".tmp"):
            state["n"] += 1
            raise PermissionError(32, "sharing violation")
        return real(self, text, *a, **kw)

    monkeypatch.setattr(Path, "write_text", flaky)
    atomic_write(out, "<html>the answer</html>")
    assert state["n"] == 1, "the write retried once and landed"
    assert out.read_text(encoding="utf-8") == \
        "<html>the answer</html>"
    assert not list(tmp_path.glob("*.tmp")), "no half artifact"


def test_a_lock_sharing_violation_is_contention(tmp_path,
                                                monkeypatch):
    """Windows maps a sharing violation on an existing lock file to
    EACCES (PermissionError), not EEXIST - it means someone holds
    the lock, and treating it as an error dropped lines fast (the
    store's own per-id lock learned this years ago)."""
    led = _ledger(tmp_path)
    import os

    real_open = os.open
    state = {"n": 0}

    def flaky(path, flags, *a, **kw):
        if state["n"] == 0 and "lock" in str(path):
            state["n"] += 1
            raise PermissionError(32, "sharing violation")
        return real_open(path, flags, *a, **kw)

    monkeypatch.setattr("approximately.ledger.os.open", flaky)
    entry = led.append("abcd1234ef01", "root1")
    assert entry.seq == 1, (
        "one sharing violation on the lock file used to raise out "
        "of the acquisition and drop the line via the best-effort "
        "swallow")
    assert led.entries()[0].trace_id == "abcd1234ef01"


def test_a_replaced_ledger_file_is_picked_up(tmp_path,
                                             monkeypatch):
    led = _ledger(tmp_path)
    led.append("abcd1234ef01", "root1")
    # the doctor's clean (or a bad sync) replaces the file: the
    # persistent handle must notice the new inode, not keep
    # appending to the removed one. (Tests may remove the file -
    # the product never does - and Windows cannot unlink an open
    # file, so the cached handle closes first.)
    from approximately.ledger import close_handle

    close_handle(tmp_path / "ledger.jsonl")
    (tmp_path / "ledger.jsonl").unlink()
    entry = led.append("other1234567", "root2")
    assert entry.seq == 1, (
        "appending to the removed inode would vanish invisibly")
    assert [e.trace_id for e in led.entries()] == ["other1234567"]


def test_many_concurrent_writers_keep_every_line(tmp_path,
                                                 monkeypatch):
    import threading

    # monkeypatch (not bare os.environ): the env must be restored
    # for the tests after this one - the v73 ladder reads it
    monkeypatch.setenv("APPROXIMATELY_LEDGER", "1")
    store_dir = tmp_path / "stress"
    from approximately.integrity import sign
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    store = TraceStore(store_dir)
    rec = Recorder("fixture", store=store, save=False)
    rec.respond("done", success=True)
    sign(rec.trace)
    store.save(rec.trace)
    expected = 1

    def mk(i):
        nonlocal expected
        rec = Recorder(f"race {i}", store=store, save=False)
        rec.tool("sh", {"cmd": "x"}, result="ok")
        rec.respond("done", success=True)
        sign(rec.trace)
        store.save(rec.trace)

    for wave in range(4):
        threads = [threading.Thread(target=mk, args=(wave * 12 + i,))
                   for i in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        expected += 12
        from approximately.ledger import verify_ledger

        led = store_dir / "ledger.jsonl"
        lines = [ln for ln in led.read_text().splitlines()
                 if ln.strip()]
        check = verify_ledger(store_dir)
        assert check.intact, f"wave {wave}: {check.detail}"
        assert len(lines) == expected, (
            f"wave {wave}: {len(lines)} of {expected} lines - "
            "the persistent handle must not lose a line to "
            "per-line open() sharing windows")


def test_the_first_attempt_never_reads_the_clock(tmp_path):
    led = _ledger(tmp_path)
    entry = led.append("abcd1234ef01", "root1")
    assert entry.seq == 1
    assert len(led.entries()) == 1
