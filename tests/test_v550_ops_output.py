"""v550: the ops-output layer meets hostile traces.

The recon found three P0s in the postmortem HTML: Step.kind and
annotation author interpolated unescaped (live <script> in the
postmortem), and a hostile created_at (year 33658 — finite, so it
survives coerce_epoch) ValueError'd report and report --all. Plus
the grade --trend letter swap (the zip paired busiest-first cards
with grade-sorted rows), fleet --trend crashes on hostile digest
snapshots, markdown injection in four bypass sites, and the door
contracts.
"""

import json
from pathlib import Path

from approximately.attributor import attribute
from approximately.diff import diff as trace_diff
from approximately.diff import first_fault
from approximately.fleet import trend_days
from approximately.grade import _week_letters
from approximately.markdown_report import render_markdown
from approximately.report import render_html
from approximately.trace import Step, Trace

ROOT = Path(__file__).resolve().parent.parent


def _trace(**kw):
    trace = Trace.from_dict({
        "id": "abcd1234ef01", "task": "ops output probe",
        "created_at": 1700000000.0,
        "steps": [{"kind": kw.pop("kind", "tool_call"),
                   "tool": kw.pop("tool", "sh"),
                   "result": kw.pop("result", "r")} | kw],
    })
    trace.success = kw.get("success", True)
    return trace


# ---- the postmortem HTML: everything a trace speaks is escaped

def test_step_kind_is_escaped():
    trace = _trace(kind="<script>alert('kind')</script>")
    text = render_html(trace, attribute(trace))
    assert "<script>alert('kind')</script>" not in text,  (
        "kind rode the page raw - the one field the escape  "
        "discipline missed")


def test_annotation_author_is_escaped():
    trace = _trace()
    trace.meta["annotations"] = [{
        "author": "<script>alert('author')</script>",
        "note": "n", "verdict": "ok"}]
    text = render_html(trace, attribute(trace))
    assert "<script>alert('author')</script>" not in text,  (
        "the annotation writer is a different party than the  "
        "reader on a shared store")


def test_a_hostile_epoch_cannot_kill_the_report():
    for bad in (1e12, -1e12):
        trace = _trace(created_at=bad)
        text = render_html(trace, attribute(trace))
        assert "year must be" not in text,  (
            "one hostile trace used to ValueError the report door  "
            "and the whole --all index with it")


def test_the_epoch_falls_back_to_the_epoch():
    from approximately.report import _utc_stamp

    assert _utc_stamp(1e12, "%Y-%m-%d") == "1970-01-01", \
        "the fallback is the epoch itself: honestly old, honestly present"


# ---- grade --trend: letters pair with their own subjects

def test_week_letters_name_their_own_subjects():
    import tempfile

    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    store = TraceStore(tempfile.mkdtemp())
    agents = ("beta", "beta", "alpha", "alpha")
    for agent, ok in zip(agents, (False, False, True, True),
                         strict=False):
        rec = Recorder("wl task", store=store, save=False)
        rec.tool("deploy", {"cmd": "x"},
                 result="ok" if ok else "boom")
        rec.respond("done" if ok else "gave up", success=ok)
        rec.trace.agent = agent
        store.save(rec.trace, stamp=False)
    window = store.list_traces()
    for trace, agent in zip(window, agents, strict=False):
        for step in trace.steps:
            step.agent = agent
    letters = _week_letters(window, key="agent", kind="agent")
    assert letters["alpha"] in ("A", "B"), \
        "the quiet clean agent used to wear the failing one's F"
    assert letters["beta"] in ("D", "F"), \
        "the busy failing agent used to wear the clean one's A"


# ---- fleet --trend: digest files are untrusted input

def test_a_non_dict_top_mode_entry_is_skipped(tmp_path):
    import datetime

    digest_dir = tmp_path / "digests"
    digest_dir.mkdir()
    day = datetime.datetime(2026, 1, 5, 12, 0, 0)
    lines = [json.dumps({"ts": day.timestamp(), "failures": 1,
                         "traces": 10,
                         "top_modes": [5, "x"]})]
    (digest_dir / "digest-2026-01-05.jsonl").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    days = trend_days(digest_dir)
    assert days, "the trend door survives the hostile entry"


def test_a_scalar_worsening_list_is_not_joined(tmp_path):
    import datetime

    digest_dir = tmp_path / "digests"
    digest_dir.mkdir()
    day = datetime.datetime(2026, 1, 5, 12, 0, 0)
    lines = [json.dumps({"ts": day.timestamp(), "failures": 1,
                         "traces": 10, "worsening": 5})]
    (digest_dir / "digest-2026-01-05.jsonl").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    days = trend_days(digest_dir)
    assert days, "a scalar worsening used to TypeError the join"


# ---- markdown: the bypass sites are inside the fence

def test_markdown_tool_names_are_escaped():
    trace = _trace(tool="**`[x](http://evil)`**")
    trace.add(Step(kind="tool_call", tool="**`[y](e)`**",
                   result="r", tokens=5000, latency_ms=100))
    trace.add(Step(kind="response", result="done"))
    trace.success = True
    text = render_markdown(trace, attribute(trace))

    bullets = [row for row in text.splitlines()
               if "Latency" in row or "# 1" in row]
    assert not any("[x](http://evil)" in row
                           and "Latency" in row
                   for row in bullets), \
        "the latency bullet used to render the hostile link live"


def test_annotation_rows_are_escaped_in_markdown():
    trace = _trace()
    trace.meta["annotations"] = [{"verdict": "**injected**",
                                  "note": "**also**",
                                  "author": "**me**"}]
    text = render_markdown(trace, attribute(trace))
    import re

    assert not re.search(r"\*\*injected\*\*", text), \
        "the annotation row used to render unescaped"


# ---- the doors: named answers, honest floors

def test_the_bisect_door_refuses_a_nan_floor(tmp_path):
    import subprocess
    import sys

    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    store = TraceStore(tmp_path)
    rec = Recorder("nan floor", store=store)
    rec.tool("deploy", {"i": 1}, result="ok")
    rec.respond("done", success=True)
    store.save(rec.trace)
    other = TraceStore(tmp_path / "other")
    rec2 = Recorder("nan floor 2", store=other)
    rec2.tool("deploy", {"i": 2}, result="CHANGED RESULT")
    rec2.respond("done", success=True)
    other.save(rec2.trace)
    r = subprocess.run(
        [sys.executable, "-m", "approximately", "--store",
         str(store.directory), "bisect", rec.trace.id, "--other",
         rec2.trace.id, "--other-store", str(other.directory),
         "--floor", "nan"],
        capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 2,  (
        "nan compares False against everything: every mutation  "
        "silently qualified as non-material")


def test_first_fault_honors_the_docstring_contract():
    a = _trace(result="same")
    a.success = True
    a.add(Step(kind="tool_call", tool="deploy", args={"i": 1},
               result="same"))
    b = _trace(result="CHANGED")
    b.success = True
    b.add(Step(kind="tool_call", tool="deploy", args={"i": 2},
               result="CHANGED"))
    td = trace_diff(a, b)
    assert first_fault(td, floor=0.8) is not None
    assert first_fault(td, floor=1.01) is not None,  (
        "the docstring contract: floor 1.01 makes any non-equal  "
        "entry qualify")
