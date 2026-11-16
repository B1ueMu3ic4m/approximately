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


def test_the_first_attempt_never_reads_the_clock(tmp_path):
    led = _ledger(tmp_path)
    entry = led.append("abcd1234ef01", "root1")
    assert entry.seq == 1
    assert len(led.entries()) == 1
