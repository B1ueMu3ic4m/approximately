"""v227: fuzz round 14 — the money entrances.

Prices tables and token counts now drive alarms; untrusted values
get the round-4 contract plus arithmetic sanity: a negative or
absurd token count cannot poison the totals, a negative rate is a
configuration error, and junk price files stay loud.
"""

import argparse
import contextlib
import io
import json
import random

import pytest

from approximately.cli import cmd_stats
from approximately.importer import _MAX_STEP_TOKENS, _genai_tokens, otlp_to_traces
from approximately.store import TraceStore

SEED = 20261002


def _span(attrs, span_id="1" * 16, parent=""):
    return {"traceId": "a" * 32, "spanId": span_id,
            "parentSpanId": parent, "name": "llm.call",
            "startTimeUnixNano": "1000000000",
            "endTimeUnixNano": "2000000000",
            "attributes": attrs}


def test_negative_tokens_clamp_to_zero():
    attrs = [{"key": "approximately.kind",
              "value": {"stringValue": "tool_call"}},
             {"key": "approximately.tokens",
              "value": {"intValue": "-500"}}]
    spans = [_span([], span_id="0" * 16),
             _span(attrs, span_id="2" * 16, parent="0" * 16)]
    traces, malformed, _seen, truncated = otlp_to_traces(
        {"resourceSpans": [{"scopeSpans": [{"spans": spans}]}]})
    assert (malformed, truncated) == (0, 0)
    assert traces[0].steps[0].tokens == 0


def test_genai_negatives_clamp_to_zero():
    assert _genai_tokens({"gen_ai.usage.prompt_tokens": -10**12,
                          "gen_ai.usage.completion_tokens": 50}) \
        == -10**12 + 50            # raw helper sums honestly...
    spans = [_span([], span_id="0" * 16),
             _span([{"key": "gen_ai.usage.prompt_tokens",
                     "value": {"intValue": "-10**12"}}],
                   span_id="2" * 16, parent="0" * 16)]
    traces, _mal, _seen, _trunc = otlp_to_traces(
        {"resourceSpans": [{"scopeSpans": [{"spans": spans}]}]})
    # ...but the import clamps: no negative tokens reach a step
    assert traces[0].steps[0].tokens == 0


def test_absurd_tokens_cap_at_sanity():
    attrs = [{"key": "approximately.kind",
              "value": {"stringValue": "tool_call"}},
             {"key": "gen_ai.usage.total_tokens",
              "value": {"intValue": "99999999999"}}]
    spans = [_span([], span_id="0" * 16),
             _span(attrs, span_id="2" * 16, parent="0" * 16)]
    traces, _mal, _seen, _trunc = otlp_to_traces(
        {"resourceSpans": [{"scopeSpans": [{"spans": spans}]}]})
    assert traces[0].steps[0].tokens == _MAX_STEP_TOKENS


def test_negative_rate_is_a_config_error(tmp_path, capsys):
    store = TraceStore(tmp_path / "s")
    table = tmp_path / "prices.json"
    table.write_text(json.dumps({"gpt-x": -3.0}), encoding="utf-8")
    args = argparse_namespace(str(store.directory), str(table))
    with pytest.raises(SystemExit) as exc:
        cmd_stats(args)
    assert exc.value.code == 2
    assert "non-negative" in capsys.readouterr().err


def test_random_price_files_never_crash(tmp_path, capsys):
    rng = random.Random(SEED)
    pool = [None, 0, -1, 1e308, "x", True, {"nested": 1}, [], 3.5,
            -0.001, 10**30]
    for i in range(40):
        table = {}
        for _ in range(rng.randint(0, 5)):
            model = rng.choice(["gpt-x", "cheap", "中文", "", "a b"])
            table[model] = rng.choice(pool)
        path = tmp_path / f"p{i}.json"
        path.write_text(json.dumps(table), encoding="utf-8")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            try:
                cmd_stats(argparse_namespace(str(tmp_path / "s"),
                                             str(path)))
            except SystemExit as exc:
                assert exc.code in (0, 2)
            except (TypeError, ValueError) as exc:
                raise AssertionError(
                    "junk price table crashed") from exc


def test_random_envelopes_keep_totals_sane(tmp_path):
    rng = random.Random(SEED + 1)
    values = [0, -5, 10**15, "x", None, [1], {"a": 1}, 42,
              99999999999, 0.5]
    for _i in range(200):
        attrs = []
        if rng.random() < 0.7:
            attrs.append({"key": rng.choice(
                ["approximately.tokens", "gen_ai.usage.total_tokens",
                 "gen_ai.usage.prompt_tokens"]),
                "value": {rng.choice(["intValue", "stringValue",
                                      "boolValue"]):
                          rng.choice(values)}})
        spans = [_span(attrs, span_id="1" * 16),
                 _span([], span_id="2" * 16, parent="1" * 16)]
        traces, _mal, _seen, _trunc = otlp_to_traces(
            {"resourceSpans": [{"scopeSpans": [{"spans": spans}]}]})
        for step in traces[0].steps:
            assert 0 <= step.tokens <= _MAX_STEP_TOKENS


def argparse_namespace(store, prices):
    return argparse.Namespace(store=store, by_agent=False,
                              by_tool=False, min_failed=None,
                              trend=False, trend_bucket_days=1,
                              since=None, price_per_1k=None,
                              prices=prices, json=True)
