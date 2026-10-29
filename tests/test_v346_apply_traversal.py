"""v346: the plan is data — data must not aim the delete.

``apply_plan`` unlinks the plan's rows; a hostile row id used to
be able to aim that unlink outside the store (an absolute id —
``Path`` join replaces the base — or a ``..`` climb). The guards
now refuse any id whose resolved parent is not the store itself.
Unreachable through the CLI and MCP doors today (both build their
plans internally), but a delete aimed by data is a loaded gun for
the next caller.
"""

import tempfile
from pathlib import Path

from approximately.retention import apply_plan
from approximately.store import TraceStore
from approximately.trace import Step, Trace


def _store_with_one():
    store = TraceStore(tempfile.mkdtemp())
    t = Trace(task="old ok", model="m")
    t.add(Step(kind="tool_call", tool="sh", result="x", tokens=5))
    t.success = True
    store.save(t)
    return store


def test_absolute_id_cannot_unlink_outside_the_store():
    store = _store_with_one()
    victim = Path(tempfile.mkdtemp()) / "victim.json"
    victim.write_text("{}", encoding="utf-8")
    evil_id = str(victim)[:-len(".json")]
    removed = apply_plan(store, {"retire": [{"id": evil_id}]})
    assert removed == 0
    assert victim.exists(), "the delete never leaves the store"


def test_dotdot_climb_is_refused_too():
    store = _store_with_one()
    outside = Path(tempfile.mkdtemp()) / "victim.json"
    outside.write_text("{}", encoding="utf-8")
    climb = f"../{outside.parent.name}/{outside.stem}"
    removed = apply_plan(store, {"retire": [{"id": climb}]})
    assert removed == 0
    assert outside.exists()


def test_legitimate_rows_still_delete():
    store = _store_with_one()
    legit = store.list_traces()[0].id
    removed = apply_plan(store, {"retire": [{"id": legit}]})
    assert removed == 1
    assert not list(store.directory.glob("*.json"))
