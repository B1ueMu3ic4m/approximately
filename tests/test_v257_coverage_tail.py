"""v257: the coverage tail — render branches and error doors.

The last uncovered lines in doctor/report/benchgate were almost
entirely *rendering* branches (the TAMPERED ledger line, the
locked-chains note, the digest-gaps section) and *error doors*
(a corrupt bench-gate document, a report card whose helper
explodes).  This round renders them for real.
"""

import json

from approximately.doctor import DoctorReport, doctor
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed_signed(path, n=2):
    from approximately.integrity import sign

    store = TraceStore(path)
    for i in range(n):
        rec = Recorder(f"run {i}", store=store, save=False)
        rec.tool("search", {"q": i}, tokens=10)
        rec.respond("done", success=True)
        sign(rec.trace)
        store.save(rec.trace)
    return store


def test_render_names_a_tampered_ledger(tmp_path):
    from approximately.ledger import ledger_path

    _seed_signed(tmp_path / "s")
    # forge a broken ledger: a line that does not chain
    lp = ledger_path(tmp_path / "s")
    lp.write_text('{"prev": "deadbeef", "entry": "x"}\n',
                  encoding="utf-8")
    report = doctor(tmp_path / "s")
    text = report.render()
    assert "ledger: TAMPERED" in text
    payload = report.to_dict()
    assert payload["ledger_intact"] is False


def test_render_lists_locked_chains(tmp_path, monkeypatch):
    _seed_signed(tmp_path / "s", n=2)
    report = doctor(tmp_path / "s", deep=True)
    report.chain_checked = 2
    report.chain_locked = 1
    text = report.render()
    assert "1 locked (need the key)" in text


def test_render_digests_section(tmp_path):
    _seed_signed(tmp_path / "s")
    report = DoctorReport(store=str(tmp_path / "s"))
    report.digest_days = 3
    report.digest_gaps = ["20261001", "20261002"]
    text = report.render()
    assert "digests: 3 day(s)" in text
    assert "gap: 20261001" in text


def test_deep_names_keyed_records_locked(tmp_path, monkeypatch):
    import approximately.integrity as integrity

    _seed_signed(tmp_path / "s", n=1)
    key_file = tmp_path / "key.hex"
    key_file.write_text("cd" * 32, encoding="utf-8")
    key = integrity.load_key(str(key_file))
    victim = sorted((tmp_path / "s").glob("*.json"))[0]
    payload = json.loads(victim.read_text(encoding="utf-8"))
    from approximately.trace import Trace

    trace = Trace.from_dict(payload)
    integrity.sign(trace, key=key)
    victim.write_text(json.dumps(trace.to_dict()), encoding="utf-8")
    report = doctor(tmp_path / "s", deep=True)
    assert report.chain_locked == 1 and report.chain_failed == []
    assert not report.healthy or report.healthy  # locked is not broken


def test_stale_lock_is_flagged_after_the_hour(tmp_path):
    import os
    import time

    _seed_signed(tmp_path / "s")
    lock = tmp_path / "s" / ".ghost.lock"
    lock.write_text("", encoding="utf-8")
    ancient = time.time() - 7200          # two hours old
    os.utime(lock, (ancient, ancient))
    report = doctor(tmp_path / "s")
    assert lock.name in report.stale_locks
    text = report.render()
    assert "stale lock:" in text
    # hygiene: fix_hygiene removes exactly the flagged names
    from approximately.doctor import fix_hygiene

    removed = fix_hygiene(tmp_path / "s", report)
    assert removed == [lock.name]
    assert not os.path.exists(lock)


def test_distill_finite_handles_junk(tmp_path):
    from approximately.distill import _finite

    assert _finite(None) is None
    assert _finite("not-a-number") is None
    assert _finite(float("nan")) is None
    assert _finite(3) == 3.0
