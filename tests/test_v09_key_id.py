"""v0.9: HMAC key-ID + rotation counter — honest verdicts across keys."""

from __future__ import annotations

import pytest

from approximately.integrity import key_id, rotate, sign, verify
from approximately.recorder import Recorder
from approximately.trace import Trace


def _trace(steps: int = 2) -> Trace:
    rec = Recorder("audit task", save=False)
    for i in range(steps):
        rec.tool(f"tool_{i}", {"n": i}, result=f"ok {i}")
    rec.respond("done")
    return rec.trace


KEY_A = b"rotate-me-a" * 3
KEY_B = b"rotate-me-b" * 3
KEY_C = b"rotate-me-c" * 3


class TestKeyIdStamping:
    def test_keyed_sign_stamps_key_id(self):
        trace = _trace()
        block = sign(trace, key=KEY_A)
        assert block["key_id"] == key_id(KEY_A)
        assert len(block["key_id"]) == 8
        assert block["rotations"] == 0

    def test_unkeyed_sign_has_no_key_id(self):
        trace = _trace()
        block = sign(trace)
        assert "key_id" not in block and "rotations" not in block
        assert verify(trace).verdict == "intact"

    def test_key_id_stable_and_distinct(self):
        assert key_id(KEY_A) == key_id(KEY_A)
        assert key_id(KEY_A) != key_id(KEY_B)


class TestWrongKeyVerdict:
    def test_wrong_key_is_not_tampered(self):
        trace = _trace()
        sign(trace, key=KEY_A)
        result = verify(trace, key=KEY_B)
        # the evidence is locked with another key, not edited —
        # reporting TAMPERED here would be a false accusation
        assert result.verdict == "wrong-key"
        assert "rotate first" in result.detail

    def test_correct_key_intact_with_provenance(self):
        trace = _trace()
        sign(trace, key=KEY_A)
        result = verify(trace, key=KEY_A)
        assert result.verdict == "intact"
        assert key_id(KEY_A) in result.detail
        assert "rotations: 0" in result.detail

    def test_tamper_still_tampered_with_correct_key(self):
        trace = _trace()
        sign(trace, key=KEY_A)
        trace.steps[0].result = "edited after signing"
        assert verify(trace, key=KEY_A).verdict == "TAMPERED"

    def test_old_blocks_without_key_id_still_verify(self):
        # back-compat: traces signed before v0.9 carry no key_id
        trace = _trace()
        sign(trace, key=KEY_A)
        trace.meta["integrity"].pop("key_id")
        assert verify(trace, key=KEY_A).verdict == "intact"


class TestRotationCounter:
    def test_counter_increments_across_chain(self):
        trace = _trace()
        sign(trace, key=KEY_A)
        for key_old, key_new in ((KEY_A, KEY_B), (KEY_B, KEY_C)):
            result = rotate(trace, old_key=key_old, new_key=key_new)
            assert result.verdict == "intact"
        block = trace.meta["integrity"]
        assert block["rotations"] == 2
        assert block["key_id"] == key_id(KEY_C)
        assert verify(trace, key=KEY_C).verdict == "intact"

    def test_rotate_refuses_wrong_old_key(self):
        trace = _trace()
        sign(trace, key=KEY_A)
        with pytest.raises(ValueError, match="wrong-key"):
            rotate(trace, old_key=KEY_B, new_key=KEY_C)

    def test_counter_survives_resign_without_rotation(self):
        trace = _trace()
        sign(trace, key=KEY_A)
        rotate(trace, old_key=KEY_A, new_key=KEY_B)
        sign(trace, key=KEY_B)  # plain re-sign preserves the counter
        assert trace.meta["integrity"]["rotations"] == 1


class TestKeyPersistence:
    def test_key_id_survives_store_roundtrip(self, tmp_path):
        from approximately.store import TraceStore

        store = TraceStore(tmp_path)
        rec = Recorder("persist", store=store, save=False)
        rec.tool("t", {}, result="r")
        rec.respond("ok")
        sign(rec.trace, key=KEY_A)
        store.save(rec.trace)

        loaded = store.load(rec.trace.id)
        assert loaded.meta["integrity"]["key_id"] == key_id(KEY_A)
        assert verify(loaded, key=KEY_A).verdict == "intact"
