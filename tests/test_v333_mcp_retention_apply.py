"""v333: the MCP retention door learns to apply — carefully.

The CLI has had ``--apply`` from the start; the MCP tool stayed
plan-only. Now it deletes too, but behind a two-flag gate: ``apply``
says what you want, ``confirm`` says you mean it — miss either and
you get a plan, never a deletion. The guards (breach evidence,
annotated traces, unreadable poison) are re-checked per file at
apply time by the same :func:`apply_plan` the CLI uses, so both
doors share one delete path and one set of vetoes.
"""

import tempfile
import time

import pytest

from approximately.mcp_server import ServerContext, _tool_retention
from approximately.store import TraceStore
from approximately.trace import Step, Trace

NOW = time.time()


def _trace(store, task, success, age_days, breached=False):
    t = Trace(task=task, model="m")
    t.add(Step(kind="tool_call", tool="sh", result="x", tokens=5))
    t.success = success
    t.created_at = NOW - age_days * 86400.0
    if breached:
        t.meta = {"budget": {"exceeded": True}}
    store.save(t)
    return t


def _ctx():
    return ServerContext(TraceStore(tempfile.mkdtemp()).directory)


def test_plan_only_stays_the_default():
    store = TraceStore(tempfile.mkdtemp())
    _trace(store, "old ok", True, 39)
    payload = _tool_retention(ServerContext(store.directory),
                              {"keep_days": 7})
    assert len(payload["retire"]) == 1
    assert "applied" not in payload
    assert list(store.directory.glob("*.json")), \
        "no apply flag, no deletion"


def test_apply_without_confirm_is_refused():
    store = TraceStore(tempfile.mkdtemp())
    _trace(store, "old ok", True, 39)
    ctx = ServerContext(store.directory)
    with pytest.raises(ValueError, match="confirm"):
        _tool_retention(ctx, {"keep_days": 7, "apply": True})
    assert list(store.directory.glob("*.json")), \
        "the single flag must not delete"


def test_apply_with_confirm_deletes_and_reports():
    store = TraceStore(tempfile.mkdtemp())
    doomed = _trace(store, "old ok", True, 39)
    young = _trace(store, "fresh ok", True, 2)
    payload = _tool_retention(ServerContext(store.directory),
                              {"keep_days": 7, "apply": True,
                               "confirm": True})
    assert payload["applied"] == 1
    assert not (store.directory / f"{doomed.id}.json").exists()
    assert (store.directory / f"{young.id}.json").exists()


def test_guards_veto_the_mcp_delete_too():
    store = TraceStore(tempfile.mkdtemp())
    annotated = _trace(store, "old ok", True, 39)
    breached = _trace(store, "old breach", True, 39, breached=True)
    store.annotate(annotated.id, "human was here")
    payload = _tool_retention(ServerContext(store.directory),
                              {"keep_days": 7, "apply": True,
                               "confirm": True})
    assert payload["applied"] == 0
    assert (store.directory / f"{annotated.id}.json").exists()
    assert (store.directory / f"{breached.id}.json").exists(), \
        "breach evidence survives both doors"
