"""v314: the digest — the shift-start brief.

``audit`` gives the cron one exit code; ``digest`` gives the on-call
human one page: weeks vs weeks, the grades, the triage queue, and
today's failed arrivals. Sections can be absent and say so; an
empty store is a refusal (a digest of nothing briefs no one); an
unknown grade floor is the audit door's refusal shape (exit 2).
"""

import argparse
import json
import tempfile
from pathlib import Path

import pytest

from approximately.cli import cmd_digest
from approximately.digest import build_digest, render_markdown
from approximately.mcp_server import ServerContext, _tool_digest
from approximately.store import TraceStore
from approximately.trace import Step, Trace


def _save(store, task, success, tokens=10):
    t = Trace(task=task, model="m")
    t.add(Step(kind="tool_call", tool="sh", result="x",
               tokens=tokens))
    t.success = success
    store.save(t)
    return t


def _store(*saves):
    store = TraceStore(tempfile.mkdtemp())
    for task, ok in saves:
        _save(store, task, ok)
    return store


def test_sections_report_themselves_when_absent():
    payload = build_digest(_store())
    assert payload["grades"] == []
    assert payload["triage"] == []
    assert payload["arrivals"] == {"failed": 0, "ok": 0, "lines": []}
    assert payload["week"] is None
    page = render_markdown(payload)
    assert "not usable yet" in page
    assert "no grades" in page
    assert "nothing to triage" in page


def test_brief_composes_the_doors():
    store = _store(("retried a finished step", False),
                   ("first ok run", True),
                   ("second ok run", True))
    payload = build_digest(store, triage_top=3, grade_floor="A")
    assert payload["grades"], "three traces grade for real"
    assert [b["grade"] for b in payload["below_floor"]]
    assert payload["triage"], "the failed run is queue material"
    assert payload["triage"][0]["trace_id"]
    # the failure landed today; the oks did too
    assert payload["arrivals"]["failed"] == 1
    assert payload["arrivals"]["ok"] == 2
    assert len(payload["arrivals"]["lines"]) == 1
    page = render_markdown(payload)
    assert "BELOW FLOOR" in page
    assert page.count("## ") == 4


def test_triage_top_clamps_the_queue():
    store = _store(("boom one", False), ("boom two", False),
                   ("fine", True))
    payload = build_digest(store, triage_top=0)
    assert payload["triage"] == []
    assert payload["arrivals"]["failed"] == 2


def test_week_section_flows_from_digest_dir(tmp_path):
    import datetime as dt

    fleet = tmp_path / "fleet"
    for day, traces, failures in (("2026-09-28", 4, 1),
                                  ("2026-10-05", 5, 1)):
        ts = dt.datetime.fromisoformat(
            f"{day}T12:00:00+00:00").timestamp()
        snap = {"ts": ts, "worsening": [],
                "stores": [{"name": "s", "traces": traces,
                            "failures": failures,
                            "failure_rate": failures / traces,
                            "est_spend": 0.5}]}
        fleet.mkdir(parents=True, exist_ok=True)
        (fleet / f"digest-{day.replace('-', '')}.jsonl").write_text(
            json.dumps(snap) + "\n", encoding="utf-8")
    store = _store(("ok", True), ("ok two", True))
    payload = build_digest(store, digest_dir=str(fleet))
    assert payload["week"] and payload["week"]["usable"]
    page = render_markdown(payload)
    assert "vs last week" in page


def test_cmd_digest_refuses_empty_store(capsys):
    args = argparse.Namespace(store=tempfile.mkdtemp(),
                              digest_dir=None, triage_top=5,
                              grade_floor=None, json=False, out=None)
    assert cmd_digest(args) == 2
    assert "briefs no one" in capsys.readouterr().err


def test_cmd_digest_refuses_unknown_floor():
    store = _store(("ok", True), ("ok two", True))
    args = argparse.Namespace(store=store.directory,
                              digest_dir=None, triage_top=5,
                              grade_floor="Z", json=False, out=None)
    assert cmd_digest(args) == 2


def test_cmd_digest_writes_markdown_and_json(tmp_path, capsys):
    store = _store(("ok", True), ("ok two", True))
    out = tmp_path / "brief.md"
    args = argparse.Namespace(store=store.directory,
                              digest_dir=None, triage_top=5,
                              grade_floor=None, json=False,
                              out=str(out))
    assert cmd_digest(args) == 0
    assert out.read_text(encoding="utf-8").startswith("# ops digest")
    args.json = True
    args.out = None
    assert cmd_digest(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["store"] == str(store.directory)


def test_mcp_digest_tool_smoke():
    store = _store(("ok", True), ("ok two", True))
    ctx = ServerContext(store.directory)
    payload = _tool_digest(ctx, {})
    assert payload["grade_kind"] == "agent"
    assert payload["grades"]
    with pytest.raises(ValueError):
        _tool_digest(ctx, {"grade_floor": "Z"})
