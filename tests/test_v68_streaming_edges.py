"""v0.68 — streaming monitor edge contract, pinned directly."""

from approximately.streaming import _is_verify_step
from approximately.trace import PLAN, TOOL_CALL, Step


def test_explicit_meta_verify_flag_wins():
    step = Step(kind=TOOL_CALL, tool="deploy", meta={"verify": True})
    assert _is_verify_step(step) is True


def test_non_tool_steps_are_never_verify_steps():
    assert _is_verify_step(Step(kind=PLAN, thought="verify the plan")) \
        is False


def test_tool_name_markers_imply_verification():
    for tool in ("verify_payment", "check_status", "confirm_order",
                 "get_record", "read_file", "fetch_url", "status"):
        assert _is_verify_step(Step(kind=TOOL_CALL, tool=tool,
                                    meta={})) is True


def test_plain_mutation_tool_is_not_verify():
    assert _is_verify_step(Step(kind=TOOL_CALL, tool="deploy",
                                meta={})) is False
