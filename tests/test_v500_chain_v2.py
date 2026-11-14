"""v500: the fence covers everything the postmortem trusts.

The tamper-evidence audit (integrity, evidence, ledger, and the
verify doors) found the core promise narrower than its slogan:
v1's chain hashed three header fields plus the steps, so a text
editor could flip ``success``, rewrite ``final_output``, forge or
erase the budget-breach stamp, and re-point the redaction
provenance — all while ``verify`` said intact. Worse, v4.2.1's
coercion boundary and v1's stamp were asymmetric: a recorder-
written 3-hour step (10.8M ms) false-FAILED its own verdict
forever. v2 closes both directions: the chain covers the coerced
view (sign and verify hash the same truth) and every postmortem
field (id, verdict, output, meta — breach stamp included);
v1 records verify under v1 rules and are NAMED as such
(intact-legacy), history is never rewritten. The evidence pack's
manifest is signed and audited in both directions; the ledger's
read-then-append holds a cross-trace lock; an unreadable file is
a named verdict (exit 6), never a traceback wearing the TAMPERED
exit code; a destroyed store reads as INCOMPLETE AUDIT, not
clean; and a missing key file is a refusal, not a silent
downgrade to a forgeable chain.
"""

import json
import subprocess
import sys
import threading
import zipfile
from pathlib import Path

import pytest

from approximately.evidence import build_evidence_pack, verify_evidence_pack
from approximately.integrity import (
    ALGORITHM,
    ALGORITHM_V1,
    _chain_v1,
    _seed_v1,
    compute_chain,
    load_key,
    sign,
    verify,
)
from approximately.store import TraceStore, stamped_breach
from approximately.trace import Step, Trace

ROOT = Path(__file__).resolve().parent.parent


def _run(*args, env=None):
    import os

    return subprocess.run(
        [sys.executable, "-m", "approximately", *args],
        capture_output=True, text=True, cwd=str(ROOT),
        env={**os.environ, **(env or {})})


def _stamp(tmp_path, **step_kw):
    from approximately.recorder import Recorder

    store = TraceStore(tmp_path)
    rec = Recorder("v5 task", store=store)
    rec.tool("sh", {"cmd": "x"}, result="ok", **step_kw)
    rec.respond("done", success=True)
    store.save(rec.trace)
    return store, rec.trace


# ---- F1: the coerced view - the recorder's own values never
# ---- false-fail their own verdict

def test_a_clamp_eligible_step_verifies_intact():
    trace = Trace(task="hang", created_at=1700000000.0)
    trace.add(Step(kind="tool_call", tool="sh",
                   latency_ms=10_800_000,  # a 3-hour hang
                   tokens=10 ** 400))
    sign(trace)
    result = verify(Trace.from_dict(trace.to_dict()))
    assert result.verdict == "intact",  (
        "v1 false-FAILED recorder-written evidence forever: the  "
        "clamp at load was not the clamp at stamp")
    view = trace.to_dict()
    assert view["steps"][0]["latency_ms"] == 10_800_000,  (
        "the stored bytes keep the raw value; the chain covers  "
        "the coerced truth")


def test_sign_and_verify_hash_the_same_view():
    trace = Trace(task="stable", created_at=1700000000.0)
    trace.add(Step(kind="tool_call", tool="sh", result="ok"))
    sign(trace)
    from approximately.integrity import _hash_view

    twice = _hash_view(_hash_view(trace))
    assert compute_chain(twice) == compute_chain(trace), \
        "normalization is idempotent: sign and verify cannot drift"


# ---- F2/F3: every postmortem field is inside the fence

def _signed_trace():
    trace = Trace(task="fence", created_at=1700000000.0)
    trace.add(Step(kind="tool_call", tool="sh", result="ok"))
    sign(trace)
    return trace


@pytest.mark.parametrize("edit", [
    lambda d: d.update(success=not d["success"]),
    lambda d: d.update(final_output="we never failed"),
    lambda d: d.update(id="different1"),
    lambda d: d["meta"].update(budget={"exceeded": True}),
    lambda d: d["steps"][0].update(result="edited"),
])
def test_every_field_edit_is_tampered(edit):
    trace = _signed_trace()
    d = trace.to_dict()
    edit(d)
    result = verify(Trace.from_dict(d))
    assert result.verdict == "TAMPERED",  (
        "v1 verified every one of these intact - the README  "
        "promise was narrower than its slogan")


def test_the_breach_stamp_is_signature_covered():
    trace = Trace(task="breach", created_at=1700000000.0)
    trace.add(Step(kind="tool_call", tool="sh", result="ok"))
    sign(trace)
    d = trace.to_dict()
    d["meta"]["budget"] = {"exceeded": False}
    forged = Trace.from_dict(d)
    assert verify(forged).verdict == "TAMPERED"
    assert stamped_breach(_signed_trace().meta) is False
    assert not stamped_breach(forged.meta),  (
        "a forged breach cannot be read off a record that failed  "
        "its own verification")


def test_redaction_provenance_is_covered():
    trace = _signed_trace()
    trace.meta["redacted"] = {"from": "abcd1234ef01"}
    sign(trace)
    d = trace.to_dict()
    d["meta"]["redacted"]["from"] = "other12345678"
    assert verify(Trace.from_dict(d)).verdict == "TAMPERED", \
        "a share copy used to be re-pointable at any original"


# ---- legacy: v1 records verify under v1 rules, and are NAMED

def _legacy_block(trace):
    chain = _chain_v1(trace)
    trace.meta["integrity"] = {
        "algorithm": ALGORITHM_V1, "keyed": False,
        "seed": _seed_v1(trace), "step_hashes": chain,
        "final": chain[-1] if chain else _seed_v1(trace),
    }
    return trace


def test_legacy_records_verify_and_name_their_format():
    trace = _legacy_block(Trace(task="old", created_at=1700000000.0))
    trace.add(Step(kind="tool_call", tool="sh", result="ok"))
    trace.meta.pop("integrity")
    _legacy_block(trace)
    result = verify(trace)
    assert result.verdict == "intact-legacy"
    assert "legacy" in result.detail
    assert result.verdict_override != "intact", \
        "the format is named, never silently rebadged"


def test_legacy_steps_still_tamper_loudly():
    trace = Trace(task="old", created_at=1700000000.0)
    trace.add(Step(kind="tool_call", tool="sh", result="ok"))
    _legacy_block(trace)
    d = trace.to_dict()
    d["steps"][0]["result"] = "edited"
    assert verify(Trace.from_dict(d)).verdict == "TAMPERED"


def test_the_new_default_is_v2():
    trace = _signed_trace()
    assert trace.meta["integrity"]["algorithm"] == ALGORITHM


# ---- F4: the pack manifest is signed and audited both ways

def _packed(tmp_path, key=b"pack-key-1"):
    store, trace = _stamp(tmp_path)
    pack = tmp_path / "pack.zip"
    build_evidence_pack(store, trace.id, pack, key=key)
    return pack, key


def test_a_signed_pack_verifies_trusted(tmp_path):
    pack, key = _packed(tmp_path)
    result = verify_evidence_pack(pack, key=key)
    assert result["manifest_ok"] and result["manifest_signed"]
    assert result["signature_ok"] is True
    assert result["chain"]["verdict"] == "intact"


def test_a_signed_pack_without_the_key_is_locked(tmp_path):
    pack, _key = _packed(tmp_path)
    result = verify_evidence_pack(pack)  # no key at all
    assert result["signature_ok"] is False
    assert result["manifest_ok"] is False,  (
        "saying TRUSTED here would be the de-coverage attack  "
        "winning by omission")


def test_a_restamp_attack_is_refused(tmp_path):
    pack, key = _packed(tmp_path)
    src = zipfile.ZipFile(pack)
    names = src.namelist()
    manifest = json.loads(src.read("manifest.json"))
    ann = json.loads(src.read("annotations.json"))
    ann.append({"trace_id": manifest["trace_id"], "verdict": "ok",
                "note": "CLEARED - no fault found"})
    ann_bytes = json.dumps(ann).encode()
    manifest.pop("signature")
    manifest["members"]["annotations.json"] = (
        hashlib_sha256(ann_bytes))
    body = dict(manifest)
    forged_sig = _fake_sig(body)
    manifest["signature"] = forged_sig
    alt = tmp_path / "forged.zip"
    with zipfile.ZipFile(alt, "w") as out:
        for name in names:
            payload = ann_bytes if name == "annotations.json" \
                else src.read(name)
            out.writestr(name, payload)
        out.writestr("manifest.json", json.dumps(
            manifest, indent=2, sort_keys=True))
    result = verify_evidence_pack(alt, key=key)
    assert result["signature_ok"] is False
    assert result["manifest_ok"] is False,  (
        "the re-stamp attack (edit member, recompute digest,  "
        "re-sign with your own key) verified TRUSTED before")


def test_a_decoverage_attack_is_named(tmp_path):
    pack, key = _packed(tmp_path)
    src = zipfile.ZipFile(pack)
    names = src.namelist()
    manifest = json.loads(src.read("manifest.json"))
    manifest["members"].pop("annotations.json")
    manifest.pop("signature")
    manifest["signature"] = _fake_sig(manifest)
    alt = tmp_path / "decovered.zip"
    with zipfile.ZipFile(alt, "w") as out:
        for name in names:
            payload = (json.dumps(manifest, indent=2, sort_keys=True)
                       if name == "manifest.json"
                       else src.read(name))
            out.writestr(name, payload)
    result = verify_evidence_pack(alt, key=key)
    assert "annotations.json" in result["uncovered"], \
        "members outside the manifest used to ride invisibly"
    assert result["manifest_ok"] is False


def _fake_sig(body):
    import hashlib
    import hmac

    return hmac.new(b"attacker-key", json.dumps(
        body, sort_keys=True, default=str).encode(),
        hashlib.sha256).hexdigest()


def hashlib_sha256(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


# ---- F5: a destroyed store reads INCOMPLETE, not clean

def test_a_destroyed_store_is_incomplete(tmp_path):
    store, _trace = _stamp(tmp_path)
    (store.directory / "destroyed01.json").write_text(
        "{torn", encoding="utf-8")
    r = _run("--store", str(store.directory), "verify", "--all",
             "--json")
    data = json.loads(r.stdout)
    assert r.returncode == 6,  (
        "the destroyed-evasion used to read exit 0 with an empty  "
        "verdict list")
    assert data["skipped"] == ["destroyed01.json"]
    assert data["summary"]["intact"] == 1
    r2 = _run("--store", str(store.directory), "verify", "--all")
    assert r2.returncode == 6 and "INCOMPLETE AUDIT" in r2.stdout


# ---- F6: concurrent finishers cannot break the ledger chain

def test_twelve_concurrent_saves_keep_the_ledger_intact(tmp_path,
                                                        monkeypatch):
    monkeypatch.setenv("APPROXIMATELY_LEDGER", "1")
    store, _trace = _stamp(tmp_path)
    ids = []
    lock = threading.Lock()

    def mk(i):
        from approximately.integrity import sign
        from approximately.recorder import Recorder

        rec = Recorder(f"race {i}", store=store, save=False)
        rec.tool("sh", {"cmd": "x"}, result="ok")
        rec.respond("done", success=True)
        sign(rec.trace)  # the ledger records stamped evidence only
        store.save(rec.trace)
        with lock:
            ids.append(rec.trace.id)

    threads = [threading.Thread(target=mk, args=(i,))
               for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    from approximately.ledger import verify_ledger

    led = store.directory / "ledger.jsonl"
    lines = (led.read_text().splitlines()
             if led.exists() else [])
    check = verify_ledger(store.directory)
    assert check.intact,  (
        "12 concurrent finishers used to stamp duplicate seqs and  "
        "break the chain permanently (no repair tool exists)")
    assert len(lines) == 13,  (
        f"12 saves + the fixture's own must all land; got {len(lines)}  "
        f"(ledger exists: {led.exists()})")


# ---- F7: an unreadable file is named, never the TAMPERED exit

def test_an_unreadable_trace_answers_unreadable(tmp_path):
    store, _trace = _stamp(tmp_path)
    (store.directory / "corrupt01ab.json").write_text(
        '{"task": "x", "id": "corrupt01ab", "steps": [',
        encoding="utf-8")
    r = _run("--store", str(store.directory), "verify", "corrupt01ab")
    assert r.returncode == 6,  (
        "the traceback used to exit 1 - the TAMPERED code - and a  "
        "CI script read crashed for tampered")
    payload = json.loads(r.stdout)
    assert payload["verdict"] == "unreadable"


# ---- F8: a missing key file is a refusal, not a downgrade

def test_an_explicit_missing_key_file_is_refused():
    with pytest.raises(ValueError, match="not found"):
        load_key("/nonexistent/key.pem")
    assert load_key() is None,  (
        "the env path stays optional: an unconfigured store is an  "
        "honest unsigned store")


def test_the_verify_door_refuses_a_missing_key_by_name(tmp_path):
    store, _trace = _stamp(tmp_path)
    r = _run("--store", str(store.directory), "verify", "--all",
             "--key-file", "/nonexistent/key.pem")
    assert r.returncode == 2 and "not found" in r.stderr
    assert "Traceback" not in r.stderr


def test_the_serve_door_refuses_a_missing_key(tmp_path):
    r = _run("--store", str(tmp_path), "webhook-serve", "--port", "0",
             "--key-file", "/nonexistent/key.pem")
    assert r.returncode == 2, \
        "a missing receiver key used to OPEN the tap silently"
    assert "not found" in r.stderr


# ---- F9: ledger absence is visible, not invisible

def test_ledger_absence_is_named_in_the_json(tmp_path):
    store, _trace = _stamp(tmp_path)
    r = _run("--store", str(store.directory), "verify", "--all",
             "--json")
    data = json.loads(r.stdout)
    assert "ledger_present" in data,  (
        "deleting ledger.jsonl used to make rollback detection  "
        "evaporate invisibly")
    assert data["ledger_present"] is False


# ---- F10: the share copy is written atomically

def test_redact_share_write_leaves_no_half_copy(tmp_path):
    store, trace = _stamp(tmp_path)
    out = tmp_path / "share.json"
    r = _run("--store", str(store.directory), "redact", trace.id,
             "--out", str(out))
    assert r.returncode == 0, r.stderr
    assert out.exists()
    leftovers = [p.name for p in tmp_path.iterdir()
                 if p.name.endswith(".tmp")]
    assert not leftovers, \
        "a crash mid-write used to leave a half-scratched share"
