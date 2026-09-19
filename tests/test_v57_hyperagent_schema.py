"""v0.57 — HyperAgent log-line schema parsing (mastdata), direct tests.

The ``<logger> - INFO - <agent>'s Response: ...`` trajectory schema
had integration coverage only through converted corpora; these tests
pin the parser's contract line by line.
"""

from __future__ import annotations

import json

from approximately.mastdata import (
    _hyperagent_turns,
    _signal_turns,
    _to_trace,
)


def _lines(*pairs):
    out = []
    for role, text in pairs:
        out.append(f"agent_bridge - INFO - {role}'s Response: {text}")
    return out


def test_turns_accumulate_continuation_lines():
    trajectory = [*_lines(("Planner", "first plan line")),
                  "agent_bridge - INFO - continuing the plan here",
                  "agent_bridge - INFO - and one more line"]
    turns = _hyperagent_turns(trajectory)
    assert turns == [("Planner",
                      ("first plan line continuing the plan here "
                       "and one more line"))]


def test_turns_split_on_each_marker():
    trajectory = _lines(("Planner", "plan"),
                        ("Editor", "edit done"))
    turns = _hyperagent_turns(trajectory)
    assert [r for r, _ in turns] == ["Planner", "Editor"]
    assert turns[1][1] == "edit done"


def test_blank_and_nonstring_lines_are_skipped():
    trajectory = [None, 42, "", "   ",
                  "agent_bridge - INFO - Planner's Response: start",
                  "", "agent_bridge - INFO - tail"]
    turns = _hyperagent_turns(trajectory)
    assert turns == [("Planner", "start tail")]


def test_lines_before_any_marker_are_dropped():
    trajectory = [("agent_bridge - INFO - init complete, "
                   "loading config"), "raw code echo with no marker",
                  *_lines(("Editor", "real turn"))]
    assert _hyperagent_turns(trajectory) == [("Editor", "real turn")]


def test_marker_with_empty_body_starts_empty_buffer():
    trajectory = [*_lines(("Planner", "")),
                  "agent_bridge - INFO - body arrives on the next line"]
    turns = _hyperagent_turns(trajectory)
    assert turns == [("Planner", "body arrives on the next line")]


def test_to_trace_maps_roles_to_step_names():
    record = {"task": "fix it", "success": False, "trajectory":
              _lines(("Planner", "think"), ("EXECUTOR-1", "act"))}
    trace = _to_trace(record)
    assert trace.meta["prose"] is True
    names = [s.tool for s in trace.steps]
    assert names == ["planner", "executor-1"]
    assert _signal_turns(trace) == 2


def test_to_trace_truncates_long_turns():
    record = {"task": "t", "success": False, "trajectory":
              _lines(("Planner", "x" * 5000))}
    trace = _to_trace(record)
    assert len(trace.steps[0].result) == 2000


def test_to_trace_dict_schema_skips_non_dicts_and_empty():
    # the schema is chosen by the FIRST trajectory element: a dict
    # first means dict-schema, where later non-dict entries are skipped
    record = {"task": "t", "success": True, "trajectory": [
        {"role": "assistant", "name": "planner",
         "content": [{"text": "hello "}, {"text": "world"}]},
        "not a dict",
        {"role": "user", "content": ""},
        {"role": "tool", "name": "grep", "content": "match"},
    ]}
    trace = _to_trace(record)
    names = [s.tool for s in trace.steps]
    assert names == ["planner", "grep"]
    # list content is element-joined (str per element), so dict
    # entries surface as their repr - asserted as-is on purpose
    assert "hello" in trace.steps[0].result
    assert "match" in trace.steps[1].result


def test_convert_roundtrip_writes_labeled_jsonl(tmp_path):
    """The HyperAgent path feeds convert_mast end to end."""
    from approximately.mastdata import convert_mast

    src = tmp_path / "source"
    src.mkdir()
    for i in range(2):
        record = {"task": f"case {i}", "success": False,
                  "failure_modes": [],
                  "note": {"options": {"Step repetition": "yes"}},
                  "trajectory": _lines(
                      ("Planner", f"plan {i}"),
                      ("Editor", f"patch {i}"))}
        (src / f"trace_{i}.json").write_text(
            json.dumps(record), encoding="utf-8")
    out = tmp_path / "out.jsonl"
    stats = convert_mast(src, out)
    lines = [json.loads(row) for row in
             out.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2
    assert all(r["meta"]["prose"] for r in lines)
    assert stats.converted == 2
