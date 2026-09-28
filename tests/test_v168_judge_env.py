"""v168: judge cache without flags — the environment default.

`APPROXIMATELY_JUDGE_CACHE` backs every --judge consumer (flag wins
when given), and the MCP `attribute` tool opens `judge` +
`judge_cache`: an agent stack can ask for the judge verdict and the
cache in one call. Judge absence still degrades to rules-only.
"""

import argparse
import json

import approximately.judge as judge_mod
from approximately.cli import _judge_kwargs
from approximately.mcp_server import ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore


def test_env_var_backs_the_flag(monkeypatch, tmp_path):
    monkeypatch.setenv("APPROXIMATELY_JUDGE_CACHE",
                       str(tmp_path / "env-cache"))
    args = argparse.Namespace(judge_cache=None)
    kwargs = _judge_kwargs(args)
    assert kwargs["cache_dir"] == tmp_path / "env-cache"
    # the flag wins over the environment
    args = argparse.Namespace(judge_cache=str(tmp_path / "flag"))
    assert _judge_kwargs(args)["cache_dir"] == tmp_path / "flag"
    # neither: no cache
    monkeypatch.delenv("APPROXIMATELY_JUDGE_CACHE")
    assert _judge_kwargs(argparse.Namespace(judge_cache=None)) == {}


def test_mcp_attribute_judge_absent_degrades(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("APPROXIMATELY_JUDGE_CACHE", raising=False)
    store = TraceStore(tmp_path / "s")
    rec = Recorder("judge me", save=False)
    rec.tool("deploy", {"env": "prod"}, result=None, error="timeout")
    rec.respond("gave up", success=False)
    store.save(rec.trace)
    ctx = ServerContext(str(store.directory))
    payload = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "attribute",
                   "arguments": {"trace": rec.trace.id,
                                 "store": str(store.directory),
                                 "judge": True}},
    }, ctx)
    result = json.loads(payload["result"]["content"][0]["text"])
    assert result["judge_used"] is False  # rules-only, no crash


def test_mcp_attribute_judge_with_cache(tmp_path, monkeypatch):
    calls = []

    def fake_request(trace, chosen_model, preset, api_key=None,
                     base_url=None):
        calls.append(1)
        return ('{"mode_id": "FM-1.3", "step_index": 0, '
                '"rationale": "timeout", "confidence": 0.9}')

    monkeypatch.setattr(judge_mod, "_judge_request", fake_request)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    store = TraceStore(tmp_path / "s")
    rec = Recorder("judge me twice", save=False)
    rec.tool("deploy", {"env": "prod"}, result=None, error="timeout")
    rec.respond("gave up", success=False)
    store.save(rec.trace)
    cache = tmp_path / "jcache"
    ctx = ServerContext(str(store.directory))
    for _ in range(2):
        payload = handle_request({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "attribute",
                       "arguments": {"trace": rec.trace.id,
                                     "store": str(store.directory),
                                     "judge": True,
                                     "judge_cache": str(cache)}},
        }, ctx)
    result = json.loads(payload["result"]["content"][0]["text"])
    assert result["judge_used"] is True
    assert len(calls) == 1  # second ask hit the cache
    assert list(cache.glob("*.json"))
