"""Night VI, round 2: the gate speaks JUnit — and reads the stamp.

``ci --format junit`` renders the gate rows as native CI annotations
(one testcase per gate, a <failure> element per breach), and
``--max-budget-breaches`` turns the live rails' stamped verdict into
a pipeline-relevant ceiling.  Exit codes never move: 0 pass, 1
breach, 2 refusal — the format changes what CI systems SEE, not what
the pipeline gates on.
"""

import argparse
import xml.etree.ElementTree as ET

import pytest

from approximately.budget import Budget, BudgetExceededError
from approximately.cli import cmd_ci
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed(store_dir, breaches=0, clean=2, fail=False):
    store = TraceStore(store_dir)
    for i in range(clean):
        with Recorder(f"clean {i}", model="m/1", store=store) as rec:
            rec.tool("t", tokens=100)
            rec.respond("done", success=not fail)
    for i in range(breaches):
        budget = Budget(tokens=10, on_exceed="stamp")
        with Recorder(f"burn {i}", model="m/1", store=store,
                      budget=budget) as rec:
            rec.tool("t", tokens=500)
            rec.respond("burned out", success=True)
    return store


def _args(store_dir, **kw):
    argv = {"store": str(store_dir), "format": None, "json": False,
            "prices": None, "min_traces": None, "since": None}
    argv.update(kw)
    return argparse.Namespace(**argv)


def test_budget_breach_gate_counts_stamped_traces(tmp_path):
    _seed(tmp_path, breaches=1)
    assert cmd_ci(_args(tmp_path, max_budget_breaches=0)) == 1
    assert cmd_ci(_args(tmp_path, max_budget_breaches=1)) == 0


def test_budget_breach_gate_only_reads_the_stamp(tmp_path):
    # a trace with no budget stamp at all is not a breach — absence
    # of rails never counts against the run
    _seed(tmp_path, breaches=0)
    assert cmd_ci(_args(tmp_path, max_budget_breaches=0)) == 0


def test_budget_breach_gate_is_one_of_the_ceilings(tmp_path):
    # it alone satisfies the "no ceilings configured" refusal
    _seed(tmp_path, breaches=1)
    assert cmd_ci(_args(tmp_path)) == 2


def test_junit_output_parses_and_matches_rows(tmp_path, capsys):
    _seed(tmp_path, breaches=1)
    rc = cmd_ci(_args(tmp_path, format="junit", max_budget_breaches=0))
    out = capsys.readouterr().out
    assert rc == 1
    root = ET.fromstring(out)
    assert root.tag == "testsuites"
    suite = root.find("testsuite")
    cases = suite.findall("testcase")
    assert len(cases) == 2  # min-traces + budget-breaches
    failures = suite.findall("testcase/failure")
    assert len(failures) == 1
    assert failures[0].get("type") == "gate-breach"
    assert suite.get("failures") == "1"
    assert suite.get("tests") == "2"
    names = [c.get("name") for c in cases]
    assert names == ["min-traces", "budget-breaches"]


def test_junit_all_pass_has_no_failure_elements(tmp_path, capsys):
    _seed(tmp_path)
    rc = cmd_ci(_args(tmp_path, format="junit", max_budget_breaches=5))
    out = capsys.readouterr().out
    assert rc == 0
    root = ET.fromstring(out)
    assert root.find("testsuite").get("failures") == "0"
    assert root.findall(".//failure") == []
    assert "budget-breaches" in out


def test_junit_refusal_is_an_errored_testcase(tmp_path, capsys):
    empty = tmp_path / "nothing"
    empty.mkdir()
    rc = cmd_ci(_args(empty, format="junit", max_failure_rate=0.1))
    out = capsys.readouterr().out
    assert rc == 2
    root = ET.fromstring(out)
    err = root.find(".//error")
    assert err is not None
    assert "empty" in err.get("message")
    assert root.find(".//testsuite").get("errors") == "1"


def test_junit_no_ceilings_refusal(tmp_path, capsys):
    _seed(tmp_path)
    rc = cmd_ci(_args(tmp_path, format="junit"))
    capsys.readouterr()
    assert rc == 2


def test_json_flag_still_the_shortcut(tmp_path, capsys):
    _seed(tmp_path)
    rc = cmd_ci(_args(tmp_path, json=True, max_budget_breaches=5))
    out = capsys.readouterr().out
    assert rc == 0
    import json
    payload = json.loads(out)
    assert payload["ok"] is True
    assert any(g["gate"] == "budget-breaches"
               for g in payload["gates"])


def test_format_wins_over_legacy_json_flag(tmp_path, capsys):
    _seed(tmp_path)
    rc = cmd_ci(_args(tmp_path, json=True, format="text",
                      max_budget_breaches=5))
    out = capsys.readouterr().out
    assert rc == 0
    assert "gate verdict" in out  # prose, not JSON


def test_integration_budget_stamp_flows_to_gate(tmp_path):
    # raise mode: the run dies mid-burn, the stamp still lands, and
    # the gate catches it post-hoc
    store = TraceStore(tmp_path)
    budget = Budget(tokens=10, on_exceed="raise")
    with pytest.raises(BudgetExceededError), \
            Recorder("die early", model="m/1", store=store,
                     budget=budget) as rec:
        rec.tool("t", tokens=999)
    assert cmd_ci(_args(tmp_path, max_budget_breaches=0)) == 1
    assert cmd_ci(_args(tmp_path, max_budget_breaches=1)) == 0
