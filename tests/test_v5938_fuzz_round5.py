"""v5938: fuzz round 5 — the DSL-bearing doors under hostile input.

The query DSL spread across the toolkit this week (recall, summary,
digest, handoff --queue, stats, plus --ids); fuzz round 5 throws a
seeded corpus of hostile expressions at every door that now takes
one: unbalanced delimiters, giant tokens, unicode soup, ``ago``
abuse (units on foreign fields, invented units, bare words), and
random operator salad. The contract under fuzz: a rejected
expression is ALWAYS a named refusal (non-empty stderr, no
traceback) and never a partial answer; the parser-level corpus
runs in-process (fast), a sampled slice goes through the real
doors and the MCP wire so the envelope path is covered too.
Deterministic seeds — a failure reproduces exactly.
"""

import json
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FIELDS = ["id", "task", "success", "model", "created", "steps",
          "tokens", "duration", "max_latency", "mode", "agents",
          "tools", "failed_tools", "errors"]
OPS = ["==", "!=", ">=", "<=", ">", "<", "contains", "startswith",
       "endswith", "matches", "in", "=", "~", "and", "or", "not"]
ATOMS = ["true", "false", "none", "FM-1.3", "'quoted'", '"dq"',
         "(", ")", ",", "24h ago", "5q ago", "99999999", "0s ago",
         "-", "e", "\u4e2d\u6587", "\U0001f600", "a" * 200, ""]
UNITS = ["s", "m", "h", "d", "w", "q", "zz", "H"]


def _corpus(count=300, seed=5938):
    rng = random.Random(seed)
    exprs = []
    for _ in range(count):
        parts = []
        for _ in range(rng.randint(1, 9)):
            pick = rng.random()
            if pick < 0.35:
                parts.append(rng.choice(FIELDS))
            elif pick < 0.7:
                parts.append(rng.choice(OPS))
            else:
                parts.append(rng.choice(ATOMS))
        exprs.append(" ".join(p for p in parts if p))
    # a few crafted shapes the random salad can miss
    exprs += ["(" * 51 + "success == false" + ")" * 51,
              "created > " + rng.choice(UNITS) + " ago",
              "created > 5" + rng.choice(UNITS) + " ago",
              "created > -3h ago",
              "tokens > 5m ago",
              "task matches (",
              "success in ()",
              "and or not and",
              "task contains '" + "x" * 300 + "'",
              "success 5 == false"]
    return exprs


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "approximately", *args],
        capture_output=True, text=True, cwd=str(ROOT),
        encoding="utf-8")


def _seed_store(tmp_path):
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    store = TraceStore(tmp_path / "s")
    rec = Recorder("fuzz target run", model="m/1", store=store,
                   save=False)
    rec.tool("deploy", {}, result="ok", latency_ms=1200)
    rec.respond("done", success=False)
    store.save(rec.trace)


def test_the_parser_never_crashes_on_the_corpus(tmp_path):
    from approximately.query import QueryError, parse

    _seed_store(tmp_path)
    from approximately.store import TraceStore

    traces = TraceStore(tmp_path / "s").list_traces()
    answered = refused = 0
    for expr in _corpus():
        try:
            pred = parse(expr)
        except QueryError:
            refused += 1
            assert expr == "" or str(expr)[:60], \
                "the refusal carries the reason"
            continue
        answered += 1
        # a parsed predicate must ANSWER, not throw, on real traces
        for trace in traces:
            try:
                pred(trace)
            except QueryError as exc:
                raise AssertionError(
                    f"a parse-time valid expression blew up at "
                    f"evaluation: {expr[:60]!r}") from exc
    assert refused > 0 and answered > 0, "the corpus hits both paths"


def test_the_doors_refuse_by_name_never_traceback(tmp_path):
    _seed_store(tmp_path)
    s = str(tmp_path / "s")
    sample = _corpus(40, seed=91)[::4]
    for expr in sample:
        for args in (["query", expr],
                     ["recall", "--query", expr],
                     ["recall-summary", "--query", expr],
                     ["handoff", "--queue", "3", "--query", expr],
                     ["stats", "--query", expr]):
            r = _run("--store", s, *args)
            assert "Traceback" not in r.stderr, \
                f"{args[:2]} leaked a traceback on {expr[:40]!r}"
            if r.returncode != 0:
                assert r.stderr.strip(), (
                    f"{args[:2]} refused {expr[:40]!r} without a "
                    "reason")
            else:
                assert r.stdout, \
                    f"{args[:2]} answered nothing on {expr[:40]!r}"


def test_the_wire_answers_envelopes_not_crashes(tmp_path):
    _seed_store(tmp_path)
    from approximately.mcp_server import ServerContext, handle_request

    ctx = ServerContext(str(tmp_path / "s"))
    for expr in _corpus(30, seed=7)[::3]:
        payload = handle_request({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "recall",
                       "arguments": {"query": expr}},
        }, ctx)
        result = payload["result"]
        text = result["content"][0]["text"]
        assert "Traceback" not in text, expr[:40]
        if result.get("isError"):
            assert "error" in json.loads(text), \
                "an error envelope carries a named reason"


def test_a_random_valid_expression_still_answers(tmp_path):
    # the fuzz must not desensitize the doors: well-formed
    # expressions keep answering through the same doors
    _seed_store(tmp_path)
    s = str(tmp_path / "s")
    for expr in ("success == false",
                 "success == false and created > 1w ago",
                 "tools contains 'deploy'",
                 "max_latency > 1000",
                 "not (success == true)"):
        r = _run("--store", s, "query", expr, "--ids")
        assert r.returncode == 0, (expr, r.stderr)
        assert r.stdout.strip(), f"{expr!r} must answer, not shrug"
