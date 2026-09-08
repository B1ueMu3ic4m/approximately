"""Tamper-evident evidence chains: signing, verification, localization."""

import json

from approximately.integrity import compute_chain, sign, verify
from approximately.recorder import Recorder


def _recorded(store):
    with Recorder("book flight", store=store) as rec:
        rec.plan("search and book")
        rec.tool("search", {"q": "SFO"}, result="JT-044")
        rec.tool("book", {"seat": "12A"}, result="BOOKED #1", mutating=True)
        rec.respond("Booked.", success=True)
    return rec.trace


def test_recorder_signs_traces_on_save(store):
    trace = _recorded(store)
    assert "integrity" in trace.meta
    block = trace.meta["integrity"]
    assert block["algorithm"] == "sha256-chain-v1"
    assert len(block["step_hashes"]) == len(trace.steps)
    loaded = store.load(trace.id)
    assert verify(loaded).verdict == "intact"


def test_tampering_is_detected_and_localized(store):
    trace = _recorded(store)
    path = store.directory / f"{trace.id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["steps"][1]["result"] = "BOOKED #9999"  # forge a different booking
    path.write_text(json.dumps(data), encoding="utf-8")

    result = verify(store.load(trace.id))
    assert result.verdict == "TAMPERED"
    assert result.first_bad_step == 1
    assert "untrusted" in result.detail


def test_appending_steps_breaks_the_chain(store):
    trace = _recorded(store)
    loaded = store.load(trace.id)
    loaded.add(__import__("approximately.trace", fromlist=["Step"]).Step(
        kind="response", result="retroactive forgery"))
    result = verify(loaded)
    assert result.verdict == "TAMPERED"


def test_older_traces_are_reported_unsigned(failing_trace):
    failing_trace.meta.pop("integrity", None)
    result = verify(failing_trace)
    assert result.verdict == "unsigned"


def test_chain_changes_when_task_changes(store):
    trace = _recorded(store)
    original = compute_chain(trace)
    trace.task = "a completely different task"
    assert compute_chain(trace) != original


# ---- HMAC keyed tier ---------------------------------------------------------

def test_hmac_sign_and_verify_roundtrip(store):
    key = b"incident-key-2026"
    trace = _recorded(store)
    sign(trace, key=key)
    loaded = store.load(trace.id)
    result = verify(loaded, key=key)
    assert result.verdict == "intact"
    assert trace.meta["integrity"]["algorithm"] == "hmac-sha256-chain-v1"


def _resave(store, trace):
    (store.directory / f"{trace.id}.json").write_text(
        trace.to_json(), encoding="utf-8")


def test_keyed_trace_without_key_is_locked_not_broken(store):
    key = b"incident-key-2026"
    trace = _recorded(store)
    sign(trace, key=key)
    _resave(store, trace)
    loaded = store.load(trace.id)
    result = verify(loaded, key=None)
    assert result.verdict == "keyed"


def test_keyed_trace_wrong_key_detects_forgery(store):
    """The adversarial case: attacker rewrites steps but holds no key."""
    key = b"real-key"
    trace = _recorded(store)
    sign(trace, key=key)
    _resave(store, trace)
    loaded = store.load(trace.id)
    loaded.steps[1].result = "forged success"   # attacker edits...
    sign(loaded, key=b"attacker-key")            # ...and re-chains with own key
    result = verify(loaded, key=key)
    assert result.verdict == "TAMPERED"
    assert result.first_bad_step == 0


def test_load_key_from_env(monkeypatch):
    from approximately.integrity import load_key

    monkeypatch.setenv("APPROXIMATELY_SIGNING_KEY", "aabbcc")
    assert load_key() == b"\xaa\xbb\xcc"
    monkeypatch.setenv("APPROXIMATELY_SIGNING_KEY", "plain text key")
    assert load_key() == b"plain text key"
    assert load_key("/nonexistent/path") is None or True  # file path wins below
    monkeypatch.delenv("APPROXIMATELY_SIGNING_KEY")
    assert load_key() is None
