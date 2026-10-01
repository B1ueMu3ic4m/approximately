"""v223: GenAI semantic conventions at OTLP import.

A tracing backend's spans carry usage under `gen_ai.usage.*`, not our
`approximately.tokens`.  Mapping them means token baselines work on
traces that never touched our recorder — the fleet can baseline a
third-party agent's burn straight from the OTLP it already exports.
"""

from approximately.anomaly import detect_token_anomalies
from approximately.importer import _genai_tokens, otlp_to_traces
from approximately.trace import TOOL_CALL


def _span(attrs, span_id="1" * 16, parent=""):
    return {"traceId": "a" * 32, "spanId": span_id,
            "parentSpanId": parent, "name": "llm.call",
            "startTimeUnixNano": "1000000000",
            "endTimeUnixNano": "2000000000",
            "attributes": [
                {"key": k, "value": {"intValue": str(v)}}
                for k, v in attrs.items()]}


def test_genai_tokens_sum_both_halves():
    assert _genai_tokens({"gen_ai.usage.prompt_tokens": "120",
                          "gen_ai.usage.completion_tokens": 80}) == 200


def test_genai_tokens_tolerant_of_junk():
    assert _genai_tokens({"gen_ai.usage.prompt_tokens": "x",
                          "gen_ai.usage.input_tokens": "40"}) == 40
    assert _genai_tokens({}) == 0


def test_foreign_burn_is_baselined():
    # a third-party agent's run: its final llm call burned tokens
    spans = [
        _span({"gen_ai.usage.prompt_tokens": 500,
               "gen_ai.usage.completion_tokens": 100},
              span_id="0" * 16),
        _span({"gen_ai.usage.prompt_tokens": 520,
               "gen_ai.usage.completion_tokens": 90},
              span_id="2" * 16, parent="0" * 16),
        _span({"gen_ai.usage.prompt_tokens": 510,
               "gen_ai.usage.completion_tokens": 95},
              span_id="3" * 16, parent="0" * 16),
        _span({"gen_ai.usage.prompt_tokens": 505,
               "gen_ai.usage.completion_tokens": 110},
              span_id="4" * 16, parent="0" * 16),
        _span({"gen_ai.usage.prompt_tokens": 515,
               "gen_ai.usage.completion_tokens": 85},
              span_id="5" * 16, parent="0" * 16),
        _span({"gen_ai.usage.prompt_tokens": 40_000,
               "gen_ai.usage.completion_tokens": 3_000},
              span_id="6" * 16, parent="0" * 16),
    ]
    traces, malformed, _seen, truncated = otlp_to_traces(
        {"resourceSpans": [{"scopeSpans": [{"spans": spans}]}]})
    assert (malformed, truncated) == (0, 0)
    trace = traces[0]
    metered = [s for s in trace.steps
               if s.kind == TOOL_CALL and s.tokens > 0]
    assert len(metered) == 5
    anomalies = detect_token_anomalies(trace)
    assert len(anomalies) == 1
    assert anomalies[0].direction == "burn"
    assert anomalies[0].tokens == 43_000


def test_genai_request_model_names_the_trace():
    spans = [_span({"gen_ai.request.model": "gpt-4o-mini"},
                   span_id="0" * 16)]
    traces, malformed, _seen, truncated = otlp_to_traces(
        {"resourceSpans": [{"scopeSpans": [{"spans": spans}]}]})
    assert (malformed, truncated) == (0, 0)
    assert traces[0].model == "gpt-4o-mini"
