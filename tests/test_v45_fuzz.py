"""v0.45 — adversarial-input robustness (deterministic fuzz round).

Every parser boundary in the toolkit meets untrusted input in
production: the query DSL from a terminal, digest files and store
records from disk, MCP lines from a socket-style stdin. These tests
throw seeded random garbage at each boundary and assert the contract:
the documented error (or a clean verdict), never an unexpected
exception, hang, or crash. Seeds are fixed — failures reproduce.
"""

from __future__ import annotations

import json
import random
import time

import pytest

from approximately.query import QueryError, parse

SEED = 20260918

# -- query DSL ------------------------------------------------------------

def _garbage_strings(n, rng):
    alphabet = ("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
                "0123456789 _().!='\"<>\\/@#%&*+-\n\t\xa0\x00ff")
    return ["".join(rng.choice(alphabet) for _ in range(rng.randint(0, 80)))
            for _ in range(n)]


def test_fuzz_query_parser_never_leaks_unexpected_errors():
    rng = random.Random(SEED)
    for text in _garbage_strings(300, rng):
        try:
            predicate = parse(text)
        except QueryError:
            continue  # the documented failure mode
        assert callable(predicate)


def test_query_parser_deep_nesting_is_rejected_not_recursive():
    deep = "(" * 5000 + "success == true" + ")" * 5000
    with pytest.raises(QueryError):
        parse(deep)


def test_query_parser_length_cap_before_any_parsing():
    with pytest.raises(QueryError):
        parse("success == " + "t" * 5000)


def test_fuzz_query_predicates_survive_odd_traces():
    from approximately.trace import Trace

    trace = Trace(id="fz", task="", steps=[])
    trace.meta["prose"] = True
    trace.success = None
    for expr in ("task contains ''", "id == 'fz'", "success != true",
                 "tokens >= -1", "steps < 999999"):
        predicate = parse(expr)
        predicate(trace)  # must not raise on a degenerate trace


# -- store doctor over corrupt files ---------------------------------------

def test_fuzz_doctor_eats_arbitrary_corrupt_files(tmp_path):
    from approximately.doctor import doctor

    rng = random.Random(SEED + 2)
    payloads = [
        "", "\x00\x01\x02", "[1, 2, 3", '{"meta": ', "null", "42",
        '{"id": 123}', '{"id": "x", "steps": "not-a-list"}',
        json.dumps({"id": "x", "steps": [{"kind": None}]}),
        "\\u escaped \ud800 lone",
    ]
    for i, payload in enumerate(payloads):
        (tmp_path / f"fuzz-{i}.json").write_text(payload,
                                                 encoding="utf-8",
                                                 errors="ignore")
    noise = bytes(rng.randrange(256) for _ in range(2048))
    (tmp_path / "fuzz-bytes.json").write_bytes(noise)
    report = doctor(tmp_path)
    # lenient-but-sane classification: bare {"id": ...} dicts parse
    # as (degenerate) traces and count as records; everything else,
    # including raw bytes, lands in corrupt
    assert report.records == 2
    assert len(report.corrupt) == len(payloads) - 2 + 1


# -- MCP line protocol ------------------------------------------------------

def test_fuzz_mcp_lines_always_answer_or_silence():
    from approximately.mcp_server import ServerContext, _handle_line

    ctx = ServerContext(".")
    rng = random.Random(SEED + 3)
    lines = [*_garbage_strings(200, rng),
             "not json", "[]", '"a string"', "123", "null",
             json.dumps({"jsonrpc": "1.0", "id": 1, "method": "x"}),
             json.dumps({"jsonrpc": "2.0", "id": 1, "method": 42}),
             json.dumps({"jsonrpc": "2.0", "method": "notify"}),
             json.dumps({"jsonrpc": "2.0", "id": {"nested": "id"},
                         "method": "ping"}),
             json.dumps({"jsonrpc": "2.0", "id": [1, None],
                         "params": {"name": []},
                         "method": "tools/call"})]
    answered = silenced = 0
    for line in lines:
        resp = _handle_line(line, ctx)
        if resp is None:
            silenced += 1
        else:
            assert resp["jsonrpc"] == "2.0"
            answered += 1
    assert answered > 0 and silenced > 0


def test_fuzz_mcp_huge_line_is_rejected_fast():
    from approximately.mcp_server import ServerContext, _handle_line

    ctx = ServerContext(".")
    huge = '{"jsonrpc": "2.0", "id": 1, "method": "ping", "pad": "' \
           + "x" * 2_000_000 + '"}'
    t0 = time.perf_counter()
    resp = _handle_line(huge, ctx)
    elapsed = time.perf_counter() - t0
    assert resp is None or "error" in resp
    assert elapsed < 1.0


# -- prose detectors over random turn soup ---------------------------------

def test_fuzz_prose_detectors_bounded_on_soup(tmp_path):
    from approximately.prose import PROSE_DETECTORS
    from approximately.trace import TOOL_CALL, Step, Trace

    rng = random.Random(SEED + 4)
    words = ["deploy", "fetch", "error", "Traceback", "the", "ok",
             "verify", "pass", "fail", "output", "αβγ", "\x7f"]
    trace = Trace(id="soup", task=" ".join(
        rng.choice(words) for _ in range(12)), steps=[])
    trace.meta["prose"] = True
    for _ in range(150):
        turn = " ".join("".join(rng.choice(words) for _ in range(
            rng.randint(1, 30))) for _ in range(4))
        trace.steps.append(Step(index=len(trace.steps),
                                kind=TOOL_CALL, tool="say",
                                args={}, result=turn))
    t0 = time.perf_counter()
    for detector in PROSE_DETECTORS:
        detector.detect(trace)
    elapsed = time.perf_counter() - t0
    assert elapsed < 5.0, f"prose soup took {elapsed:.2f}s"


def test_fuzz_prose_empty_and_whitespace_turns():
    from approximately.prose import PROSE_DETECTORS
    from approximately.trace import TOOL_CALL, Step, Trace

    trace = Trace(id="blank", task="do the thing", steps=[
        Step(index=i, kind=TOOL_CALL, tool="say", args={}, result=r)
        for i, r in enumerate(["", "   ", "\n\t", "\xa0", "ok"])
    ])
    trace.meta["prose"] = True
    for detector in PROSE_DETECTORS:
        detector.detect(trace)  # must not raise
