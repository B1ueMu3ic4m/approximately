"""v74: approximately explain — taxonomy deep dives with a live
detector bridge. The detector column is derived from the registries
(each detector class carries ``mode_id``), so a drift guard pins that
contract rather than a hand-written table."""

import json

from approximately.cli import build_parser
from approximately.detectors import ALL_DETECTORS
from approximately.explain import detectors_for_mode, explain_overview, explain_text
from approximately.mcp_server import ServerContext, handle_request
from approximately.prose import PROSE_DETECTORS
from approximately.taxonomy import FAILURE_MODES, all_modes


def test_every_detector_declares_a_valid_mode():
    for det in [*ALL_DETECTORS, *PROSE_DETECTORS]:
        assert det.mode_id in FAILURE_MODES, type(det).__name__


def test_every_mode_has_explain_text_with_fixes():
    for mode in all_modes():
        text = explain_text(mode.id)
        assert mode.definition in text
        assert "Fixes:" in text
        for i in range(1, len(mode.fixes) + 1):
            assert f"  {i}. " in text


def test_explain_fm13_lists_both_families():
    watched = detectors_for_mode("FM-1.3")
    tools = [n for f, n in watched if f == "tool"]
    prose = [n for f, n in watched if f == "prose"]
    assert "RepeatDetector" in tools and "CycleRepeatDetector" in tools
    assert "ProseRepeatDetector" in prose


def test_every_registered_detector_appears_in_its_modes_column():
    for det in ALL_DETECTORS:
        assert (type(det).__name__ in
                [n for _, n in detectors_for_mode(det.mode_id)])
    for det in PROSE_DETECTORS:
        assert (type(det).__name__ in
                [n for _, n in detectors_for_mode(det.mode_id)])


def test_mode_without_rule_detector_says_so():
    # OTHER has no mechanical detector; the text must stay honest.
    text = explain_text("OTHER")
    assert "no mechanical detector" in text


def test_explain_overview_lists_all_modes():
    table = explain_overview()
    for mode in all_modes():
        assert mode.id in table
    assert "tool = real tool-call traces" in table


def test_cli_explain_deep_dive_and_overview(capsys):
    parser = build_parser()
    rc = parser.parse_args(["explain", "FM-1.3"]).func(
        parser.parse_args(["explain", "FM-1.3"]))
    assert rc == 0
    out = capsys.readouterr().out
    assert "Step Repetition" in out and "Watched by:" in out

    rc = parser.parse_args(["explain"]).func(parser.parse_args(["explain"]))
    assert rc == 0
    assert "FM-3.3" in capsys.readouterr().out


def test_cli_explain_unknown_mode_exits_1(capsys):
    parser = build_parser()
    args = parser.parse_args(["explain", "FM-9.9"])
    assert args.func(args) == 1
    assert "unknown failure mode" in capsys.readouterr().err


def test_mcp_explain_tool_roundtrip():
    ctx = ServerContext(".")
    resp = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "explain",
                   "arguments": {"mode": "FM-2.1"}},
    }, ctx)
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert "Conversation Reset" in payload["text"]

    resp = handle_request({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "explain", "arguments": {}},
    }, ctx)
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert "FM-1.1" in payload["overview"]


def test_mcp_explain_unknown_mode_is_tool_error():
    ctx = ServerContext(".")
    resp = handle_request({
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "explain",
                   "arguments": {"mode": "NOPE"}},
    }, ctx)
    assert resp["result"]["isError"] is True


def test_detector_registry_size_unchanged():
    # explain's coverage columns promise full registries; a surprise
    # registration should be a conscious test change.
    assert len(ALL_DETECTORS) == 15
    assert len(PROSE_DETECTORS) == 8
