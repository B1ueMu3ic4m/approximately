"""v0.14: re-sign counter — how many times has this evidence been stamped?"""

from __future__ import annotations

from approximately.integrity import sign, verify
from approximately.recorder import Recorder


def _trace():
    rec = Recorder("counter task", save=False)
    rec.tool("t", {}, result="ok")
    rec.respond("done")
    return rec.trace


class TestResignCounter:
    def test_first_sign_is_one(self):
        trace = _trace()
        block = sign(trace)
        assert block["resign_count"] == 1

    def test_unsigned_trace_untouched(self):
        trace = _trace()
        assert verify(trace).detail == "trace carries no integrity block"

    def test_counter_grows_on_resign(self):
        trace = _trace()
        sign(trace)
        trace.steps[0].result = "legitimate correction"
        sign(trace)
        trace.steps[0].result = "another correction"
        block = sign(trace)
        assert block["resign_count"] == 3
        result = verify(trace)
        assert result.verdict == "intact"
        assert "re-signed 2x" in result.detail

    def test_counter_survives_rotation(self):
        from approximately.integrity import rotate

        trace = _trace()
        sign(trace, key=b"key-a" * 4)
        rotate(trace, old_key=b"key-a" * 4, new_key=b"key-b" * 4)
        assert trace.meta["integrity"]["resign_count"] == 2
        result = verify(trace, key=b"key-b" * 4)
        assert result.verdict == "intact"
        assert "re-signed 1x" in result.detail
        assert "rotations: 1" in result.detail

    def test_tamper_still_tampered_regardless_of_counter(self):
        trace = _trace()
        sign(trace)
        sign(trace)
        trace.steps[0].result = "forged after the fact"
        assert verify(trace).verdict == "TAMPERED"

    def test_unkeyed_blocks_carry_counter_too(self):
        trace = _trace()
        sign(trace)
        sign(trace)
        assert trace.meta["integrity"]["resign_count"] == 2
        assert verify(trace).verdict == "intact"
