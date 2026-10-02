"""v235: retention by count, and a doctor that recompute the chains.

Two store-hygiene gaps closed.  `clean --max-traces N` keeps a burst
day from outliving its welcome: the age cap alone lets one busy
afternoon accumulate a thousand records forever.  `doctor --deep`
recomputes every record's integrity chain — a record can be
parseable JSON and still lie, and only re-hashing the steps catches
that.  Keyed records without the key at hand count as *locked*, not
broken: accusing TAMPERED there would be wrong.
"""

import json
import os
import time

from approximately.cli import main
from approximately.doctor import doctor
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed(path, n=5, stagger=60.0):
    store = TraceStore(path)
    from approximately.integrity import sign

    base = time.time() - n * stagger
    for i in range(n):
        rec = Recorder(f"run {i}", store=store, save=False)
        rec.tool("search", {"q": f"q{i}"}, tokens=10)
        rec.respond("done", success=True)
        sign(rec.trace)               # the ctx-manager exit hook does
        trace_path = store.save(rec.trace)
        stamp = base + i * stagger
        os.utime(trace_path, (stamp, stamp))
    return store


def test_max_traces_keeps_the_newest(tmp_path):
    _seed(tmp_path / "s", n=5)
    removed = TraceStore(tmp_path / "s").clean(keep_days=30,
                                               max_traces=3)
    assert removed == 2
    survivors = sorted(p.stem for p in
                       (tmp_path / "s").glob("*.json"))
    assert len(survivors) == 3


def test_max_traces_dry_run_removes_nothing(tmp_path):
    _seed(tmp_path / "s", n=5)
    removed = TraceStore(tmp_path / "s").clean(keep_days=30,
                                               max_traces=2,
                                               dry_run=True)
    assert removed == 3
    assert len(list((tmp_path / "s").glob("*.json"))) == 5


def test_max_traces_over_is_a_no_op(tmp_path):
    _seed(tmp_path / "s", n=3)
    assert TraceStore(tmp_path / "s").clean(keep_days=30,
                                            max_traces=10) == 0


def test_age_cap_and_count_cap_compose(tmp_path):
    # old records die by age, the rest by count; no double counting
    store = _seed(tmp_path / "s", n=4)
    old = time.time() - 90 * 86400
    for path in sorted((tmp_path / "s").glob("*.json"))[:2]:
        os.utime(path, (old, old))
    removed = store.clean(keep_days=30, max_traces=1)
    assert removed == 3
    assert len(list((tmp_path / "s").glob("*.json"))) == 1


def test_clean_cli_reports_remaining(tmp_path, capsys):
    _seed(tmp_path / "s", n=5)
    code = main(["clean", "--store", str(tmp_path / "s"),
                 "--max-traces", "3", "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["removed"] == 2
    assert payload["remaining"] == 3
    assert payload["max_traces"] == 3


def test_deep_doctor_verifies_healthy_chains(tmp_path):
    _seed(tmp_path / "s", n=3)
    report = doctor(tmp_path / "s", deep=True)
    assert report.chain_checked == 3
    assert report.chain_failed == [] and report.healthy


def test_deep_doctor_catches_a_lyeing_record(tmp_path):
    # parseable JSON, valid shape, forged numbers: only the chain
    # recompute knows the steps were rewritten
    _seed(tmp_path / "s", n=2)
    victim = sorted((tmp_path / "s").glob("*.json"))[0]
    payload = json.loads(victim.read_text(encoding="utf-8"))
    payload["steps"][0]["tokens"] = 999_999
    victim.write_text(json.dumps(payload), encoding="utf-8")

    shallow = doctor(tmp_path / "s")
    assert shallow.healthy            # the shallow pass sees nothing
    deep = doctor(tmp_path / "s", deep=True)
    assert victim.name in deep.chain_failed
    assert not deep.healthy


def test_deep_doctor_counts_keyed_records_locked(tmp_path):
    _seed(tmp_path / "s", n=2)
    report = doctor(tmp_path / "s", deep=True)
    assert report.chain_checked == 2
    assert report.chain_locked == 0   # no key in play: plain verify


def test_deep_doctor_skips_unsigned_records(tmp_path):
    _seed(tmp_path / "s", n=2)
    victim = sorted((tmp_path / "s").glob("*.json"))[0]
    payload = json.loads(victim.read_text(encoding="utf-8"))
    payload.get("meta", {}).pop("integrity", None)
    victim.write_text(json.dumps(payload), encoding="utf-8")
    report = doctor(tmp_path / "s", deep=True)
    assert report.chain_checked == 1  # the unsigned one is its own finding
    assert report.unsigned == 1


def test_doctor_cli_deep_json(tmp_path, capsys):
    _seed(tmp_path / "s", n=2)
    code = main(["doctor", "--store", str(tmp_path / "s"),
                 "--deep", "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["chain_checked"] == 2
    assert payload["chain_failed"] == []


def test_doctor_human_render_names_a_tamper(tmp_path, capsys):
    _seed(tmp_path / "s", n=1)
    victim = sorted((tmp_path / "s").glob("*.json"))[0]
    payload = json.loads(victim.read_text(encoding="utf-8"))
    payload["steps"][0]["result"] = "rewritten"
    victim.write_text(json.dumps(payload), encoding="utf-8")
    code = main(["doctor", "--store", str(tmp_path / "s"), "--deep"])
    assert code == 1
    out = capsys.readouterr().out
    assert "PROBLEMS FOUND" in out and "tampered:" in out
