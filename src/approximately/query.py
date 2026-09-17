"""Query DSL: select traces from a store with an expression.

``approximately query "success == false and task contains 'payment'"``

Grammar (recursive descent, precedence or < and < not < primary):

    expr    := and_expr ("or" and_expr)*
    and_expr:= not_expr ("and" not_expr)*
    not_expr:= "not" not_expr | primary
    primary := "(" expr ")" | field OP value
    OP      := "==" "!=" ">=" "<=" ">" "<" "contains" "startswith"
    value   := 'quoted string' | number | bareword (true/false/none/FM-x.y)

Fields are trace-level: ``id task success model created steps tokens
duration mode`` — ``mode`` is the set of rule-detected failure modes,
so ``mode == FM-2.1`` means "FM-2.1 is among the detected modes".
Deliberately no ``eval``: the parser produces an AST of closures, and
only comparisons against trace fields are ever executed.
"""

from __future__ import annotations

import re
from typing import Any, Callable, List, Optional

from .trace import Trace

_TOKEN = re.compile(
    r"""\s*(?:
        (?P<op>==|!=|>=|<=|>|<)
      | (?P<lparen>\()
      | (?P<rparen>\))
      | (?P<string>'[^']*'|"[^"]*")
      | (?P<number>-?\d+(?:\.\d+)?)
      | (?P<word>[A-Za-z_][A-Za-z0-9_.\-]*)
    )""",
    re.VERBOSE)

_FIELDS = ("id", "task", "success", "model", "created", "steps",
           "tokens", "duration", "mode")

_MAX_EXPR_CHARS = 4000


class QueryError(ValueError):
    """Raised for tokenizer/parser errors (message names position)."""


def tokenize(text: str) -> List[tuple]:
    # A 10k-token expression is either a bug or an attack; both fail
    # here before the recursive parser can overflow the stack.
    if len(text) > _MAX_EXPR_CHARS:
        raise QueryError(
            f"expression longer than {_MAX_EXPR_CHARS} characters")
    tokens: List[tuple] = []
    pos = 0
    while pos < len(text):
        match = _TOKEN.match(text, pos)
        if match is None or match.end() == pos:
            rest = text[pos:].strip()
            if not rest:
                break
            raise QueryError(f"cannot tokenize near {rest[:20]!r}")
        pos = match.end()
        kind = match.lastgroup
        if kind is None:
            raise QueryError(f"cannot tokenize near {text[pos:pos + 20]!r}")
        value = match.group(kind)
        if kind == "string":
            tokens.append(("string", value[1:-1]))
        elif kind == "number":
            tokens.append(("number", float(value)))
        elif kind == "word":
            tokens.append(("word", value))
        else:
            tokens.append((kind, value))
    return tokens


def _field_getter(name: str) -> Callable[[Trace], Any]:
    if name not in _FIELDS:
        raise QueryError(
            f"unknown field {name!r} (fields: {', '.join(_FIELDS)})")
    if name == "mode":
        return _detected_modes
    if name == "created":
        return lambda t: getattr(t, "created_at", None) or 0
    if name == "tokens":
        return lambda t: sum(s.tokens for s in t.steps)
    if name == "duration":
        return lambda t: sum(s.latency_ms for s in t.steps)
    if name == "steps":
        return lambda t: len(t.steps)
    return lambda t: getattr(t, name)


def _detected_modes(trace: Trace) -> set:
    from .detectors import run_rules

    return {d.mode_id for d in run_rules(trace)}


class _Parser:
    """Recursive-descent parser producing an evaluator closure."""

    # Nesting deeper than this is nonsense in a query language and a
    # stack-overflow vector in a recursive-descent parser.
    MAX_DEPTH = 50

    def __init__(self, tokens: List[tuple]):
        self.tokens = tokens
        self.pos = 0
        self.depth = 0

    def _peek(self) -> Optional[tuple]:
        return self.tokens[self.pos] if self.pos < len(self.tokens) \
            else None

    def _next(self) -> tuple:
        token = self._peek()
        if token is None:
            raise QueryError("unexpected end of expression")
        self.pos += 1
        return token

    def parse(self) -> Callable:
        if not self.tokens:
            raise QueryError("empty expression")
        node = self._or()
        leftover = self._peek()
        if leftover is not None:
            raise QueryError(
                f"unexpected {leftover[1]!r} after end of expression")
        return node

    def _or(self) -> Callable:
        node = self._and()
        while self._matches("or"):
            right = self._and()
            node = (lambda a, b: lambda t: a(t) or b(t))(node, right)
        return node

    def _and(self) -> Callable:
        node = self._not()
        while self._matches("and"):
            right = self._not()
            node = (lambda a, b: lambda t: a(t) and b(t))(node, right)
        return node

    def _not(self) -> Callable:
        if self._matches("not"):
            inner = self._not()
            return lambda t: not inner(t)
        return self._primary()

    def _matches(self, word: str) -> bool:
        token = self._peek()
        if token is None:
            return False
        kind, value = token
        if kind == "word" and value.lower() == word:
            self.pos += 1
            return True
        if word == "(" and kind == "lparen":
            self.pos += 1
            return True
        if word == ")" and kind == "rparen":
            self.pos += 1
            return True
        return False

    def _primary(self) -> Callable:
        if self._matches("("):
            self.depth += 1
            if self.depth > self.MAX_DEPTH:
                raise QueryError(
                    f"expression nested deeper than {self.MAX_DEPTH} "
                    "levels")
            node = self._or()
            self.depth -= 1
            if not self._matches(")"):
                raise QueryError("expected closing parenthesis")
            return node
        token = self._next()
        if token[0] != "word":
            raise QueryError(f"expected a field name, got {token[1]!r}")
        getter = _field_getter(token[1].lower())
        op_token = self._next()
        op = op_token[1] if op_token[0] == "op" else \
            op_token[1].lower()
        if op not in ("==", "!=", ">=", "<=", ">", "<",
                      "contains", "startswith"):
            raise QueryError(f"expected an operator after "
                             f"{token[1]!r}, got {op!r}")
        value = self._value()
        return _comparator(getter, op, value)

    def _value(self) -> Any:
        token = self._next()
        kind, value = token
        if kind in ("string", "number"):
            return value
        lowered = value.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        if lowered == "none":
            return None
        return value


def _comparator(getter, op: str, value: Any) -> Callable:
    def evaluate(trace: Trace) -> bool:
        left = getter(trace)
        if op == "==":
            return left == value
        if op == "!=":
            return left != value
        if op in (">=", "<=", ">", "<"):
            try:
                if op == ">=":
                    return left >= value
                if op == "<=":
                    return left <= value
                if op == ">":
                    return left > value
                return left < value
            except TypeError:
                return False
        if op == "contains":
            if isinstance(left, set):
                return value in left
            return str(value) in str(left or "")
        return str(left or "").startswith(str(value))

    return evaluate


def parse(text: str) -> Callable[[Trace], bool]:
    """Compile an expression into a predicate over traces."""
    return _Parser(tokenize(text)).parse()


def select(traces: List[Trace], expression: str) -> List[Trace]:
    """All traces satisfying the expression (order preserved)."""
    predicate = parse(expression)
    return [t for t in traces if predicate(t)]
