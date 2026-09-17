"""v0.33: query DSL — tokenizer, parser, semantics, CLI.

A tiny expression language over trace records: precedence or < and <
not, parentheses, seven comparison operators, and no ``eval`` — the
parser produces closures that only ever compare trace fields.
"""

from __future__ import annotations

import json

import pytest

from approximately.cli import cmd_query
from approximately.query import QueryError, parse, select, tokenize
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _trace(success: bool, task: str, nsteps: int = 2):
    rec = Recorder(task, save=False)
    rec.trace.success = success
    for i in range(nsteps):
        rec.tool("assistant", {"i": i}, result=f"turn {i}")
    return rec.trace


@pytest.fixture()
def traces():
    return [_trace(True, "fix the payment bug"),
            _trace(False, "write the report"),
            _trace(False, "fix the login bug", nsteps=6)]


class TestTokenizer:
    def test_operators_strings_numbers_words(self):
        tokens = tokenize("mode == FM-2.1 and steps >= 2.5 or 'x y'")
        kinds = [k for k, _ in tokens]
        assert kinds[0] == "word" and kinds[1] == "op"
        assert ("number", 2.5) in tokens
        assert ("string", "x y") in tokens

    def test_garbage_raises_with_context(self):
        with pytest.raises(QueryError, match="cannot tokenize"):
            tokenize("task contains 'unterminated")


class TestSemantics:
    def test_and_binds_tighter_than_or(self, traces):
        got = select(traces, "task contains fix or task contains report "
                             "and success == false")
        # or(a, and(b, c)) — the payment trace matches the left arm
        assert [t.task for t in got] == ["fix the payment bug",
                                         "write the report",
                                         "fix the login bug"]

    def test_not_with_parentheses(self, traces):
        got = select(traces, "not (task contains fix)")
        assert [t.task for t in got] == ["write the report"]

    def test_numeric_and_boolean_comparisons(self, traces):
        assert [t.task for t in select(traces, "steps >= 6")] == \
            ["fix the login bug"]
        assert [t.task for t in select(traces, "success == true")] == \
            ["fix the payment bug"]
        assert [t.task for t in select(traces, "success != false")] == \
            ["fix the payment bug"]

    def test_contains_on_task_text(self, traces):
        assert [t.task for t in
                select(traces, "task contains 'payment'")] == \
            ["fix the payment bug"]

    def test_startswith(self, traces):
        assert [t.task for t in
                select(traces, "task startswith write")] == \
            ["write the report"]

    def test_mode_membership_query(self, traces):
        # no failures recorded in these clean synthetic traces
        assert select(traces, "mode == FM-2.6") == []

    def test_type_mismatch_ordering_is_false_not_error(self, traces):
        # task is a string; ordering against a number must not raise
        assert select(traces, "task >= 5") == []


class TestErrors:
    @pytest.mark.parametrize("expr", [
        "task =", "bogus == 1", "task ==", "(task contains x",
        "task contains x bogus", "", "task contains 'a' extra",
    ])
    def test_syntax_errors_raise(self, expr, traces):
        with pytest.raises(QueryError):
            select(traces, expr)

    def test_quoted_value_with_keyword_inside(self, traces):
        got = select(traces, "task contains 'and'")
        assert got == []

    def test_deeply_nested_expression_rejected(self):
        expr = "(" * 5000 + "task contains x" + ")" * 5000
        with pytest.raises(QueryError):
            parse(expr)

    def test_long_not_chain_rejected(self):
        with pytest.raises(QueryError):
            parse("not " * 5000 + "success == true")

    def test_oversized_expression_rejected_before_tokenizing(self):
        with pytest.raises(QueryError, match="longer than"):
            parse("task contains " + "x" * 5000)


class TestCli:
    def _store(self, tmp_path):
        store = TraceStore(str(tmp_path))
        for t in (_trace(True, "alpha one"), _trace(False, "beta two")):
            store.save(t)
        return store

    def test_cli_text_output(self, tmp_path, capsys):
        self._store(tmp_path)
        args = type("A", (), {"store": str(tmp_path),
                              "expression": "success == false",
                              "json": False})()
        assert cmd_query(args) == 0
        out = capsys.readouterr().out
        assert "beta two" in out and "1 matching trace(s)" in out

    def test_cli_json_output(self, tmp_path, capsys):
        self._store(tmp_path)
        args = type("A", (), {"store": str(tmp_path),
                              "expression": "task contains beta",
                              "json": True})()
        assert cmd_query(args) == 0
        payload = json.loads(capsys.readouterr().out)
        assert len(payload) == 1
        assert payload[0]["task"] == "beta two"

    def test_cli_bad_expression_exits(self, tmp_path):
        self._store(tmp_path)
        args = type("A", (), {"store": str(tmp_path),
                              "expression": "task ??",
                              "json": False})()
        with pytest.raises(SystemExit):
            cmd_query(args)
