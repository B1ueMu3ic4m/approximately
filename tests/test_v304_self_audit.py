"""v304: the self-audit batch — v3.1.0.

Three things the toolkit runs on itself: (1) a price catalog on
file that cannot be parsed is an audit FINDING, not a bare
refusal — the 3am door diagnoses the broken table it would
otherwise trip over; (2) the README's advertised numbers are
tested against the code (tool count, door list, the VERSIONING
link); (3) the startup gate joins the perf wall.
"""

import argparse
import json
import re
from pathlib import Path

from approximately.cli import cmd_audit
from approximately.mcp_server import _TOOLS, ServerContext, _tool_audit
from approximately.prices import set_rate
from approximately.store import TraceStore
from approximately.trace import Step, Trace


def _seed(tmp_path):
    store = TraceStore(tmp_path)
    t = Trace(task="r", model="m")
    t.add(Step(kind="tool_call", tool="sh", result="ok"))
    t.success = True
    store.save(t)
    return store


def _audit_args(tmp_path, **kw):
    base = {"store": str(tmp_path), "digest_dir": None,
            "spend_ceiling": None, "failure_budget": None,
            "deep": False, "fix": False, "fail_on_worsening": False,
            "prices": None, "since": None,
            "max_failure_rate": None, "max_tokens": None,
            "max_budget_breaches": None, "max_result_chars": None,
            "max_latency_ms": None, "max_repeated_actions": None,
            "max_steps": None, "grade_floor": None,
            "triage_top": None, "json": True}
    base.update(kw)
    return argparse.Namespace(**base)


def test_audit_catalog_clean_and_corrupt(tmp_path):
    _seed(tmp_path)
    set_rate(tmp_path, "gpt-x", 0.5)
    buf = io_string()
    assert cmd_audit(_audit_args(tmp_path)) == 0
    payload = json.loads(buf.getvalue())
    assert payload["prices_catalog"] == {"corrupt": False,
                                         "models": 1}
    (Path(tmp_path) / "prices.json").write_text("{bad",
                                                encoding="utf-8")
    buf = io_string()
    assert cmd_audit(_audit_args(tmp_path)) == 1
    payload = json.loads(buf.getvalue())
    assert payload["prices_catalog"]["corrupt"] is True
    assert payload["ok"] is False


def io_string():
    import contextlib
    import io

    buf = io.StringIO()
    ctx = contextlib.redirect_stdout(buf)
    global _CTX
    _CTX = ctx
    ctx.__enter__()
    return buf


def test_audit_max_spend_with_corrupt_refuses(tmp_path, capsys):
    _seed(tmp_path)
    (Path(tmp_path) / "prices.json").write_text("{bad",
                                                encoding="utf-8")
    try:
        cmd_audit(_audit_args(tmp_path, max_spend=10.0))
        raise AssertionError("should refuse")
    except SystemExit as exc:
        assert exc.code == 2
    capsys.readouterr()


def test_mcp_audit_catalog_finding(tmp_path):
    _seed(tmp_path)
    (Path(tmp_path) / "prices.json").write_text("{bad",
                                                encoding="utf-8")
    rep = _tool_audit(ServerContext(str(tmp_path)), {})
    assert rep["prices_catalog"]["corrupt"] is True
    assert rep["ok"] is False


def test_readme_numbers_match_the_code():
    readme = Path("README.md").read_text(encoding="utf-8")
    m = re.search(r"(\d+) MCP tools", readme)
    assert m and int(m.group(1)) == len(_TOOLS), (
        m.group(1) if m else "no claim", len(_TOOLS))


def test_readme_doors_all_exist():
    readme = Path("README.md").read_text(encoding="utf-8")
    doors = set(re.findall(r"`approximately ([a-z][a-z-]+)", readme))
    src = Path("src/approximately/cli.py").read_text(encoding="utf-8")
    registered = set(
        re.findall(r'add_parser\(\s*"([a-z][a-z-]+)"', src))
    registered |= set(
        re.findall(r'add_parser\(\s*\n?\s*"([a-z][a-z-]+)"', src))
    unknown = doors - registered
    assert not unknown, f"README cites doors that do not exist: {unknown}"


def test_versioning_doc_is_linked_and_real():
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "docs/VERSIONING.md" in readme
    vdoc = Path("docs/VERSIONING.md").read_text(encoding="utf-8")
    for word in ("Major", "Minor", "Patch", "batch", "milestone"):
        assert word in vdoc
