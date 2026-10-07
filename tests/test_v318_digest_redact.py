"""v318: the digest holds the handoff's redaction rule.

The handoff never shares unscrubbed; the digest did — its page
names tasks verbatim and ``--post`` ships them to a webhook, so a
secret an agent was holding could ride the shift brief out of the
machine. ``--redact`` scrubs the payload (JSON mode) and the page
(markdown and post body) through the builtin secret patterns, and
``redact_text``/``redact_value`` make the scrub public for any
other surface that renders store text.
"""

import argparse
import json
import tempfile

from approximately.cli import cmd_digest
from approximately.mcp_server import ServerContext, _tool_digest
from approximately.redact import redact_text
from approximately.store import TraceStore
from approximately.trace import Step, Trace

SECRET = "AKIAIOSFODNN7EXAMPLE"  # the docs' example aws key


def _store():
    store = TraceStore(tempfile.mkdtemp())
    for task, ok in ((f"deploy with {SECRET}", False),
                     ("retry deploy", False), ("ok run", True)):
        t = Trace(task=task, model="m")
        t.add(Step(kind="tool_call", tool="sh", result="x",
                   tokens=5))
        t.success = ok
        store.save(t)
    return store


def _args(store, **kw):
    base = {"store": store.directory, "digest_dir": None,
            "triage_top": 5, "grade_floor": None, "json": False,
            "out": None, "post": None, "redact": False}
    base.update(kw)
    return argparse.Namespace(**base)


def test_redact_text_counts_its_hits():
    page, hits = redact_text(f"deploy with {SECRET} now")
    assert hits == {"aws_key": 1}
    assert "[REDACTED:aws_key]" in page
    assert SECRET not in page


def test_digest_redact_scrubs_the_page():
    store = _store()
    assert cmd_digest(_args(store)) == 0  # baseline sanity below
    args = _args(store, redact=True)
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert cmd_digest(args) == 0
    page = buf.getvalue()
    assert SECRET not in page
    assert "[REDACTED:aws_key]" in page


def test_digest_redact_scrubs_the_payload():
    import contextlib
    import io
    store = _store()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert cmd_digest(_args(store, json=True, redact=True)) == 0
    payload = json.loads(buf.getvalue())
    texts = json.dumps(payload)
    assert SECRET not in texts
    assert "[REDACTED:aws_key]" in texts


def test_digest_unredacted_by_default():
    import contextlib
    import io
    store = _store()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert cmd_digest(_args(store)) == 0
    assert SECRET in buf.getvalue()


def test_mcp_digest_honors_redact():
    store = _store()
    ctx = ServerContext(store.directory)
    raw = _tool_digest(ctx, {})
    assert SECRET in json.dumps(raw)
    scrubbed = _tool_digest(ctx, {"redact": True})
    text = json.dumps(scrubbed)
    assert SECRET not in text
    assert "[REDACTED:aws_key]" in text
