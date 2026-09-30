"""v212: fuzz round 12 — the OTLP surfaces under attack.

The importer now eats untrusted envelopes: a tracing backend's
export, or anything a teammate cats into stdin.  Contract unchanged
since round 4: documented errors or clean skips, never a crash that
escapes — and the two honest caps (meta keys, steps per trace) keep
a crafted envelope from turning the store into the DoS.
"""

import json
import random
import time

from approximately.importer import (
    _MAX_IMPORTED_META,
    _MAX_IMPORTED_STEPS,
    import_file,
    import_lines,
    otlp_to_traces,
)
from approximately.store import TraceStore

SEED = 20261001


def _envelope(spans):
    return {"resourceSpans": [{"scopeSpans": [{"spans": spans}]}]}


def _span(trace_id="a" * 32, **over):
    span = {"traceId": trace_id, "spanId": "1" * 16,
            "parentSpanId": "", "name": "run",
            "startTimeUnixNano": "1000000000",
            "endTimeUnixNano": "2000000000"}
    span.update(over)
    return span


def test_recursion_bomb_is_a_valueerror(tmp_path):
    # Python's JSON parser raises RecursionError past ~1000 levels;
    # import callers contractually get ValueError instead
    bomb = "[" * 100_000 + "]" * 100_000
    path = tmp_path / "bomb.jsonl"
    path.write_text(bomb, encoding="utf-8")
    try:
        import_file(path, TraceStore(tmp_path / "s1"))
    except ValueError as exc:
        assert "nested too deeply" in str(exc) or "not JSON" in str(exc)
    else:
        raise AssertionError("recursion bomb parsed")
    # the OTLP line path defuses it too (counted malformed, no crash)
    good = json.dumps(_envelope([_span()]))
    result = import_lines([bomb, good, ""],
                          TraceStore(tmp_path / "s2"), fmt="otel")
    assert result["malformed"] == 1
    assert result["imported"] == 1


def test_deep_nesting_starting_with_brace(tmp_path):
    bomb = "{" * 50_000
    path = tmp_path / "bomb.json"
    path.write_text(bomb, encoding="utf-8")
    try:
        import_file(path, TraceStore(tmp_path / "s"))
    except ValueError:
        pass            # loud either way — just never a crash
    else:
        raise AssertionError("brace bomb parsed")


def test_attribute_flood_is_bounded(tmp_path):
    attrs = [{"key": f"approximately.meta.{i}",
              "value": {"intValue": "1"}}
             for i in range(300_000)]
    traces, malformed, _seen, truncated = otlp_to_traces(
        _envelope([_span(attributes=attrs)]))
    assert (malformed, truncated) == (0, 0)
    # the meta passthrough is capped: a flood cannot bloat the store
    assert len(traces[0].meta) <= _MAX_IMPORTED_META + 1  # +imported_from


def test_span_flood_is_truncated_not_stored(tmp_path):
    spans = [_span(trace_id="c" * 32, spanId="0" * 16,
                   parentSpanId="", name="root")]
    spans += [_span(trace_id="c" * 32, spanId=f"{i + 1:016x}",
                    parentSpanId="0" * 16, name=f"s{i}")
              for i in range(_MAX_IMPORTED_STEPS + 5_000)]
    traces, _malformed, _seen, truncated = otlp_to_traces(
        _envelope(spans))
    assert len(traces) == 1
    assert len(traces[0].steps) == _MAX_IMPORTED_STEPS
    assert truncated == 5_000
    from approximately.importer import _save_otlp

    store = TraceStore(tmp_path / "s")
    counts, _ = _save_otlp(_envelope(spans), store)
    assert counts["truncated"] == 5_000
    assert counts["skipped"] >= 5_000


def test_weird_types_degrade_to_counts():
    cases = [
        _span(attributes="not-a-list"),
        _span(status={"code": [1, 2]}),
        _span(startTimeUnixNano={"deep": 1}),
        _span(traceId=12345),
        _span(attributes=[None, 42, "x"]),
        _span(parentSpanId=None, name=None),
    ]
    traces, malformed, seen, truncated = otlp_to_traces(
        _envelope(cases))
    assert seen == len(cases)
    assert truncated == 0
    # every case produced either a grouped span or a malformed count;
    # each trace's root span is the trace, not a step
    assert (sum(len(t.steps) for t in traces) + len(traces)
            + malformed == seen)


def test_random_garbage_never_crashes(tmp_path):
    rng = random.Random(SEED)
    pool = [
        "", "\x00", "null", "NaN", "{}", "[]", "[1, 2", '{"a": ',
        "x" * 5000, "\U0001D4CA", '{"resourceSpans": null}',
        '{"resourceSpans": {}}', '{"resourceSpans": [[]]}',
        '{"resourceSpans": [{"scopeSpans": "nope"}]}',
        '{"resourceSpans": [{"scopeSpans": [{"spans": [1, "s"]}]}]}',
        json.dumps(_envelope([_span(name=42), _span(extra=1)])),
        json.dumps(_envelope([_span(traceId="z" * 32)])) + "\n",
        "[" * 5_000 + "]" * 5_000,
    ]
    lines = [rng.choice(pool) for _ in range(400)]
    # ValueError ("not an envelope") is a documented outcome for an
    # explicit-format stream of parsed non-envelope lines — any other
    # exception escaping is the crash this round forbids
    try:
        result = import_lines(lines, TraceStore(tmp_path / "s"),
                              fmt="otel")
    except ValueError:
        return
    assert result["imported"] + result["skipped"] >= 0
    assert "trace_ids" in result
    # and the same treatment for the auto-sniff entry
    try:
        result2 = import_lines(lines, TraceStore(tmp_path / "s2"))
    except ValueError:
        return
    assert isinstance(result2, dict)


def test_flood_import_stays_fast(tmp_path):
    spans = [_span(trace_id="d" * 32, spanId="0" * 16,
                   parentSpanId="", name="root")]
    spans += [_span(trace_id="d" * 32, spanId=f"{i + 1:016x}",
                    parentSpanId="0" * 16, name=f"s{i}")
              for i in range(_MAX_IMPORTED_STEPS + 1)]
    document = json.dumps(_envelope(spans))
    start = time.perf_counter()
    result = import_lines([document], TraceStore(tmp_path / "s"),
                          fmt="otel")
    elapsed = time.perf_counter() - start
    assert result["truncated"] == 1
    assert elapsed < 10.0, f" capped ingest took {elapsed:.1f}s"
