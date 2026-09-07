
from approximately.recorder import Recorder
from approximately.replayer import CONSISTENT, DIVERGED, REPRODUCED, replay
from approximately.trace import TOOL_CALL


def _scripted_executor(script):
    """script: {tool_name: result_or_exception}"""

    def execute(step):
        for name, outcome in script.items():
            if step.tool == name:
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome
        return "unhandled tool"

    return execute


def test_replay_consistent_on_identical_executor(failing_trace):
    def executor(step):
        if step.tool == "search_flights":
            return "JT-044 $870"
        if step.tool == "book_flight":
            return "BOOKED #B-2231"
        return ""

    diff = replay(failing_trace, executor)
    assert diff.verdict == CONSISTENT
    assert diff.match_rate == 1.0


def test_replay_diverges_when_result_changes(failing_trace):
    def executor(step):
        return "prices changed!"

    diff = replay(failing_trace, executor)
    assert diff.verdict == DIVERGED
    assert diff.match_rate < 1.0
    divergent = [s for s in diff.steps if not s.match]
    assert divergent and "diverged" in divergent[0].headline


def test_replay_reproduces_same_failure_at_same_step():
    from approximately.recorder import Recorder

    with Recorder("flaky tool", save=False) as rec:
        rec.tool("ping", {}, result="pong")
        rec.tool("detonate", {}, error="RuntimeError: fuse lit")

    def executor(step):
        if step.tool == "detonate":
            raise RuntimeError("fuse lit")
        return "pong"

    diff = replay(rec.trace, executor)
    assert diff.verdict == REPRODUCED
    assert diff.match_rate == 1.0  # same failure counts as faithful


def test_replay_error_vs_success_diverges():
    from approximately.recorder import Recorder

    with Recorder("flaky tool", save=False) as rec:
        rec.tool("ping", {}, result="pong")
        rec.tool("detonate", {}, error="RuntimeError: fuse lit")

    diff = replay(rec.trace, lambda step: "fixed, no explosion")
    assert diff.verdict == DIVERGED


def test_replay_skips_non_tool_steps(failing_trace):
    calls = []

    def executor(step):
        calls.append(step.index)
        return step.result

    replay(failing_trace, executor)
    kinds = [s.kind for s in failing_trace.steps if s.index in calls]
    assert set(kinds) == {TOOL_CALL}


def test_replay_threshold_sensitivity(failing_trace):
    quote = "total price 870 USD including taxes and fees"
    with Recorder("price check", save=False) as rec:
        rec.tool("quote", {}, result=quote)

    exact = replay(rec.trace, lambda s: quote, threshold=0.99)
    assert exact.verdict == CONSISTENT

    near = replay(rec.trace,
                  lambda s: quote.replace("870", "871"), threshold=0.5)
    assert near.verdict == CONSISTENT

    strict = replay(rec.trace,
                    lambda s: quote.replace("870", "871"), threshold=0.99)
    assert strict.verdict == DIVERGED
