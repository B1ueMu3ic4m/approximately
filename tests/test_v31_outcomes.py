"""v0.31: outcome-level FM-3.2 — completion claims never checked.

``ProseOutcomeVerifyDetector`` reads the execution record: a closing
message that asserts resolution with zero outcome signals anywhere in
the record (no test summary, pass/fail count, or error trace) is an
unchecked claim. Execution-shaped language ("executed successfully")
is deliberately not a claim.
"""

from __future__ import annotations

from approximately.prose import ProseOutcomeVerifyDetector
from approximately.recorder import Recorder

DET = ProseOutcomeVerifyDetector()

CLAIM = ("We have successfully resolved the issue by updating the "
         "parser. The task is complete.")
ANALYSIS = "The failing snippet shows the off-by-one in the loop bounds."
RUN_FAIL = "3 failed, 2 passed in 1.2s — AssertionError: expected 4"
RUN_PASS = "17 passed in 0.9s"


def _trace(turns, final_output=None):
    rec = Recorder("fix the parser bug", save=False)
    rec.trace.meta["prose"] = True
    rec.plan("fix the bug")
    for turn in turns:
        rec.tool("assistant", {}, result=turn)
    rec.respond(final_output or "done", success=True)
    return rec.trace


class TestFires:
    def test_claim_without_any_outcome_signal(self):
        det = DET.detect(_trace(["looking at the code", ANALYSIS, CLAIM]))
        assert det is not None and det.mode_id == "FM-3.2"
        assert det.confidence == 0.7
        assert "never checked" in det.evidence[0]

    def test_claim_from_recorded_final_output(self):
        det = DET.detect(_trace([ANALYSIS, "wrapping up"],
                                final_output=CLAIM))
        assert det is not None and det.mode_id == "FM-3.2"

    def test_claim_in_final_turn_thought(self):
        rec = Recorder("fix the bug", save=False)
        rec.trace.meta["prose"] = True
        rec.plan("fix the bug")
        rec.tool("assistant", {}, result=ANALYSIS)
        rec.tool("assistant", {}, result="all checks look good")
        rec.respond(CLAIM, success=True)
        assert DET.detect(rec.trace) is not None


class TestSilent:
    def test_failure_signal_somewhere_means_it_ran(self):
        det = DET.detect(_trace([RUN_FAIL, "so close", CLAIM]))
        assert det is None

    def test_success_signal_means_it_ran(self):
        det = DET.detect(_trace([RUN_PASS, ANALYSIS, CLAIM]))
        assert det is None

    def test_execution_shaped_language_is_not_a_claim(self):
        turns = [("The script executed successfully and printed "
                  "the report."), ANALYSIS]
        det = DET.detect(_trace(turns))
        assert det is None

    def test_no_completion_claim(self):
        det = DET.detect(_trace([ANALYSIS,
                                 "here is my analysis of the root cause"]))
        assert det is None

    def test_single_turn_trace_too_small(self):
        det = DET.detect(_trace([CLAIM]))
        assert det is None
