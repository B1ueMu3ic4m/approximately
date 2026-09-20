"""v0.67 — issue-ready Markdown postmortem export."""

from __future__ import annotations

import argparse

from approximately.cli import cmd_report
from approximately.markdown_report import _esc, render_markdown
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store(tmp_path):
    store = TraceStore(str(tmp_path / "traces"))
    rec = Recorder("fix the checkout 500 on empty carts", save=False)
    rec.trace.id = "md-1"
    rec.tool("read_file", {"path": "cart/views.py"},
             result="def checkout(request): ...")
    rec.tool("edit_file", {"path": "cart/views.py"},
             result="added the empty-cart guard")
    rec.tool("run_tests", {"cmd": "pytest -q"},
             result="3 failed, 9 passed")
    rec.respond("These changes have successfully fixed the checkout 500.",
                success=False)
    store.save(rec.trace)
    return store


def test_markdown_renders_verdict_and_evidence(tmp_path):
    store = _store(tmp_path)
    from approximately.attributor import attribute

    trace = store.load("md-1")
    report = attribute(trace)
    md = render_markdown(trace, report)
    assert "## Postmortem:" in md
    assert "`md-1`" in md
    assert "### Evidence" in md
    assert "### Suggested fixes" in md
    assert "### Timeline" in md
    assert "3 failed, 9 passed" in md


def test_markdown_escapes_user_text(tmp_path):
    store = _store(tmp_path)
    from approximately.attributor import attribute

    trace = store.load("md-1")
    trace.task = "inject **bold** and [links](x) here"
    report = attribute(trace)
    md = render_markdown(trace, report)
    assert "\\*\\*bold\\*\\*" in md
    assert "\\[links\\](x)" in md


def test_esc_neutralizes_markdown_significants():
    assert _esc("**bold**") == "\\*\\*bold\\*\\*"
    assert _esc("`code`") == "\\`code\\`"
    assert _esc("[x](y)") == "\\[x\\](y)"


def test_cli_markdown_flag_writes_file(tmp_path, capsys):
    store = _store(tmp_path)
    out = tmp_path / "postmortem.md"
    rc = cmd_report(argparse.Namespace(
        store=str(store.directory), trace="md-1", all=False, judge=False,
        output=str(out), markdown=True, mermaid=None))
    text = out.read_text(encoding="utf-8")
    assert rc == 0
    assert "## Postmortem:" in text
    assert "wrote markdown postmortem" in capsys.readouterr().out


def test_markdown_is_stable_across_calls(tmp_path):
    store = _store(tmp_path)
    from approximately.attributor import attribute

    trace = store.load("md-1")
    r1 = render_markdown(trace, attribute(trace))
    r2 = render_markdown(trace, attribute(trace))
    assert r1 == r2
