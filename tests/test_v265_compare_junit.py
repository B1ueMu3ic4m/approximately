"""Night VI, round 7: the deployment gate speaks JUnit too.

``compare --format junit`` mirrors the one gateable verdict (new
failure modes under --fail-on-new-modes) as a failing testcase;
deltas ride along as informational cases.  Refusals stay exit 2 with
an <error> testcase.  Verdicts are mirrored, never invented — the
JUnit adds native CI rendering, not new ceilings.
"""

import argparse
import xml.etree.ElementTree as ET

from approximately.cli import _ci_junit_error, _compare_junit, cmd_compare
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed(store_dir, fail_mode="fm-a", failures=0):
    store = TraceStore(store_dir)
    for i in range(6):
        with Recorder(f"run {i}", model="m/1", store=store) as rec:
            rec.tool("t", tokens=10)
            rec.respond("done", success=i >= failures)
    return store


def _args(base, cand, **kw):
    argv = {"baseline": str(base), "candidate": str(cand),
            "format": None, "json": False, "prices": None,
            "fail_on_new_modes": False, "since": None}
    argv.update(kw)
    return argparse.Namespace(**argv)


def _two_stores(tmp_path):
    base = tmp_path / "base"
    cand = tmp_path / "cand"
    _seed(base, failures=0)            # clean baseline: no modes
    _seed(cand, failures=1)            # candidate shows a failure
    return base, cand


def _make_new_mode(path):
    # a failure mode only the candidate shows: a mutating call with
    # no verification afterwards
    store = TraceStore(path)
    with Recorder("novel failure", model="m/1", store=store) as rec:
        rec.tool("book", {"seat": "1A"}, result="BOOKED",
                 mutating=True)
        rec.respond("done", success=False)


def test_junit_mirrors_the_armed_gate(tmp_path, capsys):
    base, cand = _two_stores(tmp_path)
    _make_new_mode(cand)
    rc = cmd_compare(_args(base, cand, format="junit",
                           fail_on_new_modes=True))
    out = capsys.readouterr().out
    assert rc == 1
    root = ET.fromstring(out)
    suite = root.find("testsuite")
    assert suite.get("failures") == "1"
    failure = suite.find("testcase/failure")
    assert failure is not None
    assert "new failure mode" in failure.get("message")


def test_junit_disarmed_gate_reports_but_passes(tmp_path, capsys):
    base, cand = _two_stores(tmp_path)
    _make_new_mode(cand)
    rc = cmd_compare(_args(base, cand, format="junit"))
    out = capsys.readouterr().out
    assert rc == 0
    root = ET.fromstring(out)
    assert root.find("testsuite").get("failures") == "0"
    names = [c.get("name") for c in root.findall("testsuite/testcase")]
    assert "new-failure-modes" in names


def test_junit_informational_cases_carry_deltas(tmp_path, capsys):
    base, cand = _two_stores(tmp_path)
    rc = cmd_compare(_args(base, cand, format="junit"))
    out = capsys.readouterr().out
    assert rc == 0
    root = ET.fromstring(out)
    cases = {c.get("name"): c.get("value")
             for c in root.findall("testsuite/testcase")}
    assert "failure-rate" in cases and "tokens-delta" in cases
    assert cases["tokens-delta"].startswith(("+", "-"))


def test_junit_refusal_is_error_xml(tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    base, _ = _two_stores(tmp_path)
    rc = cmd_compare(_args(base, empty, format="junit",
                           fail_on_new_modes=True))
    out = capsys.readouterr().out
    assert rc == 2
    root = ET.fromstring(out)
    assert "empty" in root.find(".//error").get("message")


def test_renderer_is_honest_about_spend_cases():
    payload = {
        "baseline": {"store": "b", "traces": 1, "failures": 0,
                     "failure_rate": 0.0, "tokens": 10, "modes": []},
        "candidate": {"store": "c", "traces": 1, "failures": 0,
                      "failure_rate": 0.0, "tokens": 20, "modes": []},
        "new_modes": [], "gone_modes": [], "tokens_delta": 10,
        "spend": {"baseline": 0.01, "candidate": 0.02,
                  "unpriced_tokens": 0},
    }
    root = ET.fromstring(_compare_junit(payload, gated=False))
    names = [c.get("name") for c in root.findall("testsuite/testcase")]
    assert "spend-delta" in names
    assert root.find("testsuite").get("tests") == "4"


def test_refusal_xml_helper_is_shared():
    root = ET.fromstring(_ci_junit_error("why"))
    assert root.find(".//error").get("message") == "why"


def test_json_shortcut_still_works(tmp_path, capsys):
    import json
    base, cand = _two_stores(tmp_path)
    rc = cmd_compare(_args(base, cand, json=True))
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["baseline"]["traces"] == 6
