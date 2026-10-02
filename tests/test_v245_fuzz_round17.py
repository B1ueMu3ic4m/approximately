"""v245: fuzz round 17 — the scaffold, the stamp, and the parser.

Round contract unchanged: documented errors or clean skips, never a
crash.  New surfaces this round: `approximately init` meeting a
directory that fights back (a .gitignore that is itself a
directory, a read-only tree), `store.save(stamp=True)` meeting a
trace whose meta is not a dict, and the extended query grammar
meeting combinatorial nonsense.
"""

import pytest

from approximately.cli import main
from approximately.query import select
from approximately.recorder import Recorder
from approximately.scaffold import init_scaffold
from approximately.store import TraceStore
from approximately.trace import Step, Trace

# --- init vs a hostile directory --------------------------------------

def test_gitignore_as_a_directory_is_refused_not_a_crash(tmp_path):
    (tmp_path / ".gitignore").mkdir()
    statuses = init_scaffold(tmp_path)
    assert statuses[str(tmp_path / ".gitignore")] in ("refused",
                                                      "skipped")
    assert statuses[str(tmp_path / "prices.json")] == "written"


def test_workflow_path_blocked_by_a_directory(tmp_path):
    blocked = tmp_path / ".github" / "workflows"
    blocked.mkdir(parents=True)
    (blocked / "agent-gate.yml").mkdir()
    statuses = init_scaffold(tmp_path)
    assert statuses[str(blocked / "agent-gate.yml")] == "skipped"


def test_prices_as_a_directory_is_refused(tmp_path):
    (tmp_path / "prices.json").mkdir()
    statuses = init_scaffold(tmp_path)
    assert statuses[str(tmp_path / "prices.json")] == "skipped"


def test_init_survives_readonly_tree(tmp_path):
    readonly = tmp_path / "ro"
    readonly.mkdir()
    readonly.chmod(0o555)
    try:
        statuses = init_scaffold(readonly)
        assert set(statuses.values()) <= {"written", "refused"}
    finally:
        readonly.chmod(0o755)


# --- save vs a trace with junk meta -----------------------------------

def test_save_survives_non_dict_meta(tmp_path):
    store = TraceStore(tmp_path / "s")
    trace = Trace(task="junk meta", id="junk-1")
    trace.meta = "not a dict at all"
    trace.add(Step(kind="response", result="done"))
    path = store.save(trace)          # must not raise
    back = store.load("junk-1")
    assert back is not None and back.task == "junk meta"
    assert path.exists()


def test_save_survives_none_meta(tmp_path):
    store = TraceStore(tmp_path / "s")
    trace = Trace(task="none meta", id="none-1")
    trace.meta = None
    trace.add(Step(kind="response", result="done"))
    store.save(trace)
    assert store.load("none-1") is not None


# --- the extended grammar vs combinatorial nonsense -------------------

def _traces():
    rec = Recorder("book a flight", save=False)
    rec.tool("search", {}, result="hits")
    rec.respond("done", success=True)
    return [rec.trace]


def test_nested_value_list_parses_and_matches_nothing():
    # a nested list is legal syntax; it just never equals a scalar
    found = select(_traces(), "task in (('a', 'b'))")
    assert found == []


def parse_guard(expr):
    from approximately.query import parse

    return parse(expr)


def test_mixed_operators_chain_cleanly():
    found = select(_traces(),
                   "task contains 'flight' and tools in ('search') "
                   "and success == true")
    assert len(found) == 1


def test_in_empty_list_matches_nothing():
    assert select(_traces(), "tools in ()") == []


def test_deeply_parenthesized_value_lists_parse():
    found = select(_traces(),
                   "task in ('book a flight', 'other', 'more') or "
                   "(task endswith 'x' or task matches '^book')")
    assert len(found) == 1


def test_cli_query_garbage_is_an_error_not_a_traceback(tmp_path):
    store = TraceStore(tmp_path / "s")
    rec = Recorder("ok", save=False)
    rec.respond("done", success=True)
    store.save(rec.trace)
    # the CLI door converts the parse error into a clean exit, not
    # a traceback
    with pytest.raises(SystemExit):
        main(["query", "--store", str(tmp_path / "s"),
              "tools in (('a')"])
