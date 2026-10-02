"""v237: fuzz round 16 — the CSV surface, deep-doctor liars, and a
concurrent-writer stampede.

Round contract unchanged: documented errors or clean skips, never a
crash.  New this round: the CSV door just became a foreign-text
surface (formula injection — a cell beginning ``= + - @`` executes
when the file opens in Excel/Sheets, so it gets the standard
leading-quote defense), ``doctor --deep`` recomputes attacker-
hand-editable chains, and eight threads saving to one store must
lose nothing and leave the ledger intact.
"""

import csv
import json
import threading

from approximately.cli import main
from approximately.doctor import doctor
from approximately.exporter import export_store
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store(path, n=3):
    from approximately.integrity import sign

    store = TraceStore(path)
    for i in range(n):
        rec = Recorder(f"run {i}", store=store, save=False)
        rec.tool("search", {"q": i}, tokens=10)
        rec.respond("done", success=True)
        sign(rec.trace)               # the ctx-manager exit hook does
        store.save(rec.trace)
    return store


# --- csv hostile cells ------------------------------------------------

def test_csv_formula_injection_gets_quoted(tmp_path):
    store = TraceStore(tmp_path / "s")
    for payload in ("=cmd|' /C calc'!A0",
                    "+1+1",
                    "-2+3",
                    "@SUM(1)",
                    "\t=tab formula"):
        rec = Recorder(f"f {payload[:6]}", store=store, save=False)
        rec.tool("note", {}, result=payload)
        rec.respond("done", success=True)
        store.save(rec.trace)
    out = tmp_path / "s.csv"
    export_store(store, out, fmt="csv")
    with out.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    originals = {"=cmd|' /C calc'!A0", "+1+1", "-2+3", "@SUM(1)",
                 "\t=tab formula"}
    got = [r[12] for r in rows[1:] if r[6] == "tool_call"]
    assert len(got) == 5
    # export orders by trace id, so match content, not save order
    assert {c[1:] for c in got} == originals
    for cell in got:
        assert cell.startswith("'")


def test_csv_normal_negative_text_stays_readable(tmp_path):
    # the defense quotes a leading minus too — documented trade:
    # untrusted text beats a pretty spreadsheet
    store = TraceStore(tmp_path / "s")
    rec = Recorder("neg", store=store, save=False)
    rec.tool("score", {}, result="-3 penalty points")
    rec.respond("done", success=True)
    store.save(rec.trace)
    out = tmp_path / "s.csv"
    export_store(store, out, fmt="csv")
    with out.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[1][12] == "'-3 penalty points"


def test_csv_none_tool_and_agent_are_blank(tmp_path):
    store = TraceStore(tmp_path / "s")
    rec = Recorder("plain", store=store, save=False)
    rec.observe("just looking")
    rec.respond("done", success=True)
    store.save(rec.trace)
    out = tmp_path / "s.csv"
    export_store(store, out, fmt="csv")
    with out.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[1][7] == "" and rows[1][8] == ""


# --- deep-doctor liars ------------------------------------------------

def _tamper(path, mutate):
    victim = sorted(path.glob("*.json"))[0]
    payload = json.loads(victim.read_text(encoding="utf-8"))
    mutate(payload)
    victim.write_text(json.dumps(payload), encoding="utf-8")
    return victim


def test_deep_doctor_survives_chopped_chain(tmp_path):
    _store(tmp_path / "s")
    _tamper(tmp_path / "s",
            lambda p: p["meta"]["integrity"].__setitem__(
                "step_hashes", p["meta"]["integrity"]["step_hashes"][:1]))
    report = doctor(tmp_path / "s", deep=True)
    assert not report.healthy and len(report.chain_failed) == 1


def test_deep_doctor_survives_garbage_chain_shapes(tmp_path):
    _store(tmp_path / "s", n=2)
    _tamper(tmp_path / "s",
            lambda p: p["meta"].__setitem__(
                "integrity", {"algorithm": "sha256-chain-v1",
                              "step_hashes": "not-a-list",
                              "seed": None, "final": 7}))
    report = doctor(tmp_path / "s", deep=True)
    # the stamp still names a known algorithm, so it claims to be a
    # chain — and the chain does not verify: tampered evidence, not
    # a missing stamp.  The honest record beside it still verifies.
    assert report.chain_checked == 2
    assert len(report.chain_failed) == 1
    assert not report.healthy


def test_deep_doctor_survives_unknown_algorithm(tmp_path):
    _store(tmp_path / "s")
    _tamper(tmp_path / "s",
            lambda p: p["meta"]["integrity"].__setitem__(
                "algorithm", "xor-v0"))
    report = doctor(tmp_path / "s", deep=True)
    assert not report.chain_failed     # unsigned-classified, not tampered
    assert report.chain_checked == 2   # the two honest stamps still verify


def test_deep_doctor_every_record_lies(tmp_path):
    # all liars, one verdict: the doctor names every one and stays up
    _store(tmp_path / "s", n=3)
    for victim in sorted((tmp_path / "s").glob("*.json")):
        payload = json.loads(victim.read_text(encoding="utf-8"))
        payload["task"] = "rewritten by an intruder"
        victim.write_text(json.dumps(payload), encoding="utf-8")
    report = doctor(tmp_path / "s", deep=True)
    assert len(report.chain_failed) == 3 and not report.healthy


# --- clean edges ------------------------------------------------------

def test_clean_max_traces_zero_is_refused(tmp_path, capsys):
    _store(tmp_path / "s")
    code = main(["clean", "--store", str(tmp_path / "s"),
                 "--max-traces", "0"])
    assert code == 2
    assert "rm -rf" in capsys.readouterr().err
    assert len(list((tmp_path / "s").glob("*.json"))) == 3


def test_clean_max_traces_negative_is_refused(tmp_path):
    _store(tmp_path / "s")
    code = main(["clean", "--store", str(tmp_path / "s"),
                 "--max-traces", "-5"])
    assert code == 2
    assert len(list((tmp_path / "s").glob("*.json"))) == 3


# --- concurrent writers -----------------------------------------------

def test_eight_threads_save_without_loss(tmp_path):
    store = TraceStore(tmp_path / "s")
    errors = []

    def worker(k):
        try:
            for i in range(10):
                rec = Recorder(f"w{k} run {i}", store=store,
                               save=False)
                rec.tool("search", {"q": i}, tokens=5)
                rec.respond("done", success=True)
                store.save(rec.trace)
        except Exception as exc:            # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(k,))
               for k in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert errors == []
    assert len(list((tmp_path / "s").glob("*.json"))) == 80
    assert len(store.list_traces()) == 80


def test_concurrent_annotate_and_save(tmp_path):
    store = TraceStore(tmp_path / "s")
    ids = []
    for i in range(6):
        rec = Recorder(f"seed {i}", store=store, save=False)
        rec.respond("done", success=False)
        ids.append(store.save(rec.trace))
    lock = threading.Lock()

    def annotator():
        for tid in ids:
            with lock:
                store.annotate(tid, "checked", verdict="confirmed")

    def saver(k):
        for i in range(5):
            rec = Recorder(f"extra {k}-{i}", store=store, save=False)
            rec.respond("done", success=True)
            store.save(rec.trace)

    threads = [threading.Thread(target=annotator)] + \
        [threading.Thread(target=saver, args=(k,)) for k in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert len(store.annotations()) == 6
    assert len(store.list_traces()) == 26     # 6 seed + 4x5 savers
