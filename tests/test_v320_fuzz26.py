"""Fuzz 26: poison in the new doors — digest, retention, redact.

The chain contract again, for the surfaces this night added: each
door's output is the next door's untrusted input. A hostile store
(null-byte tasks, zero/absent timestamps, hostile markdown in task
text, unreadable files) must produce a brief that survives, a plan
that classifies, and a page that stays a document — header and
fence injection cannot restructure the shift brief because task
text is whitespace-collapsed onto one line.
"""

import json
import tempfile

from approximately.digest import build_digest, render_markdown
from approximately.mcp_server import ServerContext, _tool_digest
from approximately.redact import redact_text
from approximately.retention import apply_plan, retention_plan
from approximately.store import TraceStore
from approximately.trace import Step, Trace

HOSTILE_TASKS = [
    "deploy with \x00 null byte",
    "```python\nimport os\n```",
    "## injected header\n\n# another",
    "x" * 10_000,
    "task with \u202e reversed\u202d control",
]


def _hostile_store(tasks):
    store = TraceStore(tempfile.mkdtemp())
    for i, task in enumerate(tasks):
        t = Trace(task=task, model="m")
        t.add(Step(kind="tool_call", tool="sh", result="x" * 100,
                   tokens=10 ** 6))
        t.success = (i % 2 == 1)
        store.save(t)
    return store


def test_digest_survives_the_poisoned_store():
    store = _hostile_store([*HOSTILE_TASKS, "honest failure"])
    payload = build_digest(store, triage_top=3)
    page = render_markdown(payload)
    assert "```" not in page, "fence injection restructured the page"
    for line in page.splitlines():
        if line.startswith("# "):
            assert "injected" not in line, \
                "a task injected a header line"
    json.dumps(payload)  # the payload must stay serializable


def test_tool_digest_survives_the_poisoned_store():
    store = _hostile_store(HOSTILE_TASKS)
    payload = _tool_digest(ServerContext(store.directory), {})
    text = json.dumps(payload, default=str)
    assert "error" not in text or "trace_failure" in text
    assert "triage" in payload or "error" in text


def test_retention_classifies_the_poisoned_store():
    store = _hostile_store(["old one", "old two", "fresh one"])
    for t in store.list_traces():
        t.created_at = -5.0  # hostile: negative epoch
        store.save(t)
    plan = retention_plan(store, keep_days=30, now=1_800_000_000.0)
    assert len(plan["retire"]) == 3  # epoch 0 is ancient: all retire
    assert apply_plan(store, plan) == 3


def test_retention_leaves_poison_for_doctor():
    store = TraceStore(tempfile.mkdtemp())
    (store.directory / "poison.json").write_text(
        "\x00 not json", encoding="utf-8")
    plan = retention_plan(store, keep_days=7)
    assert plan["retire"] == []
    assert plan["kept"]["unreadable"] == 1
    assert (store.directory / "poison.json").is_file()


def test_redact_scrubs_the_poisoned_page():
    page, hits = redact_text(
        "task ```code``` AKIAIOSFODNN7EXAMPLE \x00 end")
    assert "AKIAIOSFODNN7EXAMPLE" not in page
    assert "[REDACTED:aws_key]" in page
    assert hits["aws_key"] == 1


def test_chained_doors_over_one_poisoned_store():
    """redact -> digest -> retention: the full night's chain."""
    store = _hostile_store(
        ["hold AKIAIOSFODNN7EXAMPLE then fail", "ok", "ok"])
    payload = build_digest(store, grade_floor="A")
    scrubbed, _hits = redact_text(render_markdown(payload))
    assert "AKIAIOSFODNN7EXAMPLE" not in scrubbed
    plan = retention_plan(store, keep_days=1)
    assert isinstance(plan["retire"], list)
    json.dumps({"page": scrubbed, "plan": plan})
