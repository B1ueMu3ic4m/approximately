"""v224: adapters feed the token family for real.

Two disconnects fixed.  (1) The LangChain/LangGraph handler never
recorded the model's completion — `on_llm_start` wrote a plan step
and the answer (with its usage) vanished.  (2) Every adapter passed
`tokens=` into `Recorder.tool`'s `**meta`, so `Step.tokens` stayed 0
and the token-baseline family starved on exactly the data it was
built for.  `tokens` is now a first-class recorder parameter, the
LangChain handler captures `on_llm_end`, and LlamaIndex payloads get
usage extraction — all shapes duck-typed, no framework installed.
"""

from approximately.anomaly import detect_token_anomalies
from approximately.contrib.langgraph import (
    ApproximatelyCallbackHandler,
    _response_text,
    _usage_tokens,
)
from approximately.contrib.llamaindex import ApproximatelyHandler
from approximately.contrib.llamaindex import _usage_tokens as _lx_usage_tokens

# -- LangChain response shapes ------------------------------------------------

class _Gen:
    def __init__(self, text=None, message=None, info=None):
        self.text = text
        self.message = message
        self.generation_info = info


class _Response:
    def __init__(self, generations=None, llm_output=None,
                 usage_metadata=None):
        self.generations = generations or []
        self.llm_output = llm_output or {}
        self.usage_metadata = usage_metadata


def test_llm_output_token_usage():
    response = _Response(
        llm_output={"token_usage": {"total_tokens": 137}})
    assert _usage_tokens(response) == 137


def test_chat_message_response_metadata():
    msg = {"content": "hi", "response_metadata":
           {"token_usage": {"total_tokens": 55}}}
    response = _Response(generations=[[_Gen(message=msg)]])
    assert _usage_tokens(response) == 55


def test_usage_metadata_shapes():
    gen = _Gen(message={"content": "x",
                        "usage_metadata": {"total_tokens": 7}})
    assert _usage_tokens(_Response(generations=[[gen]])) == 7
    assert _usage_tokens(_Response(
        usage_metadata={"total_tokens": 9})) == 9
    assert _usage_tokens(_Response()) == 0


def test_response_text_prefers_generation_text():
    response = _Response(generations=[[_Gen(text="the answer")]])
    assert _response_text(response) == "the answer"
    msg = {"content": ["part1", "part2"]}
    response = _Response(generations=[[_Gen(message=msg)]])
    assert "part1" in _response_text(response)


# -- the handler end to end ---------------------------------------------------

def test_on_llm_end_records_completion_and_tokens():
    handler = ApproximatelyCallbackHandler("book a flight")
    handler.on_chat_model_start({}, [{"role": "user",
                                      "content": "hi"}])
    response = _Response(
        generations=[[_Gen(text="booking now")]],
        llm_output={"token_usage": {"total_tokens": 210}})
    handler.on_llm_end(response)
    steps = handler.recorder.trace.steps
    llm = [s for s in steps if s.tool == "llm"]
    assert len(llm) == 1
    assert llm[0].tokens == 210
    assert llm[0].kind == "tool_call"
    assert "booking now" in llm[0].result


def test_adapter_trace_feeds_token_anomalies():
    # the whole point: a real-shaped adapter trace enters the
    # token-baseline family without anyone hand-filling tokens
    handler = ApproximatelyCallbackHandler("burn run")
    for tokens in (100, 90, 110, 95, 105):
        handler.on_llm_start({}, prompts=["prompt"])
        handler.on_llm_end(_Response(
            generations=[[_Gen(text="ok")]],
            llm_output={"token_usage": {"total_tokens": tokens}}))
    handler.on_llm_start({}, prompts=["prompt"])
    handler.on_llm_end(_Response(
        generations=[[_Gen(text="panic")]],
        llm_output={"token_usage": {"total_tokens": 30_000}}))
    anomalies = detect_token_anomalies(handler.recorder.trace)
    assert len(anomalies) == 1
    assert anomalies[0].tokens == 30_000
    assert anomalies[0].direction == "burn"


# -- LlamaIndex payload shapes --------------------------------------------------

def test_llamaindex_payload_usage_dict():
    assert _lx_usage_tokens(
        {"usage": {"total_tokens": 4242}}, None) == 4242
    assert _lx_usage_tokens(
        {"usage": {"prompt_tokens": 100, "completion_tokens": 30}},
        None) == 130
    assert _lx_usage_tokens(
        {"usage": {"prompt_token_count": 10,
                   "candidate_token_count": 5}}, None) == 15


def test_llamaindex_response_token_usage(tmp_path):
    response = type("R", (), {"additional_kwargs": {
        "token_usage": {"total_tokens": 77}}})()
    assert _lx_usage_tokens({}, response) == 77


def test_llamaindex_handler_records_tokens():
    handler = ApproximatelyHandler("llmIndex run")
    handler.on_event_end("LLM", {
        "response": "the completion",
        "usage": {"total_tokens": 640},
    })
    (llm,) = [s for s in handler.recorder.trace.steps
              if s.tool == "llm"]
    assert llm.tokens == 640
    assert "the completion" in llm.result


def test_llamaindex_without_usage_stays_clean():
    handler = ApproximatelyHandler("no usage")
    handler.on_event_end("LLM", {"response": "plain"})
    (llm,) = [s for s in handler.recorder.trace.steps
              if s.tool == "llm"]
    assert llm.tokens == 0
