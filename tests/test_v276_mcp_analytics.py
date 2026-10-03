"""Night VI, round 20: the new analytics become agent-callable.

``budget_sim`` (sizing door) and ``spend_forecast`` (days-to-ceiling)
join the MCP surface — 38 tools.  Validation mirrors the CLI doors:
a simulation with no ceiling proves nothing, a usd ceiling without
prices is refused, the digest directory must exist.
"""

import json

from approximately.mcp_server import _TOOLS, ServerContext, _tool_budget_sim, _tool_spend_forecast
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed(tmp_path, tokens=(1_000, 2_000, 8_000)):
    store = TraceStore(tmp_path / "s")
    with Recorder("the burn", model="m/1", store=store,
                  save=False) as rec:
        for i, t in enumerate(tokens):
            rec.tool(f"step{i}", {"i": i}, tokens=t)
        rec.respond("done", success=True)
    store.save(rec.trace)
    return store, rec.trace


def test_tools_registered_with_schemas():
    names = {t["name"] for t in _TOOLS}
    assert {"budget_sim", "spend_forecast"} <= names
    sim = next(t for t in _TOOLS if t["name"] == "budget_sim")
    assert sim["inputSchema"]["required"] == ["trace"]
    fc = next(t for t in _TOOLS if t["name"] == "spend_forecast")
    assert fc["inputSchema"]["required"] == ["digest_dir"]


def test_budget_sim_trips_and_saves(tmp_path):
    store, trace = _seed(tmp_path)
    ctx = ServerContext(str(store.directory))
    payload = _tool_budget_sim(ctx, {
        "store": str(store.directory), "trace": trace.id,
        "tokens": 5_000})
    assert payload["would_trip"] is True
    assert payload["trip_step"] == 2
    assert payload["saved_tokens"] == 0  # 8k step IS the last step


def test_budget_sim_refusals(tmp_path):
    store, trace = _seed(tmp_path)
    ctx = ServerContext(str(store.directory))
    for args in (
            {"store": str(store.directory), "trace": trace.id},
            {"store": str(store.directory), "trace": trace.id,
             "usd": 1.0},
            {"store": str(store.directory), "trace": trace.id,
             "tokens": 100, "prices": {"m/1": -1}},
            {"store": str(store.directory), "trace": "ghost",
             "tokens": 100},
    ):
        try:
            _tool_budget_sim(ctx, args)
            raise AssertionError(f"no refusal for {args}")
        except KeyError:
            pass


def test_spend_forecast_over_a_digest(tmp_path):
    digest = tmp_path / "d"
    digest.mkdir()
    for i, spend in enumerate([0.5, 1.5]):
        stamp = f"2026100{i + 1}"
        line = json.dumps({
            "ts": 1791000000 + i * 86400,
            "stores": [{"name": "s", "path": "/s", "traces": 1,
                        "est_spend": spend,
                        "spend_unpriced_tokens": 0}],
            "worsening": []}, sort_keys=True)
        (digest / f"digest-{stamp}.jsonl").write_text(
            line + "\n", encoding="utf-8")
    ctx = ServerContext(str(tmp_path))
    payload = _tool_spend_forecast(ctx, {
        "digest_dir": str(digest), "ceiling": 1.0})
    assert payload["usable"] is True
    assert payload["days_to_ceiling"] == 0
    assert len(payload["projection"]) == 14


def test_spend_forecast_refusals(tmp_path):
    ctx = ServerContext(str(tmp_path))
    try:
        _tool_spend_forecast(ctx, {"digest_dir": str(tmp_path /
                                                   "nothing")})
        raise AssertionError("no refusal for missing dir")
    except KeyError:
        pass
    digest = tmp_path / "d"
    digest.mkdir()
    try:
        _tool_spend_forecast(ctx, {"digest_dir": str(digest),
                                   "horizon_days": 0})
        raise AssertionError("no refusal for zero horizon")
    except KeyError:
        pass
    # one day of history: a forecast that refuses to guess
    line = json.dumps({"ts": 1791000000.0,
                       "stores": [{"name": "s", "path": "/s",
                                   "traces": 1, "est_spend": 1.0,
                                   "spend_unpriced_tokens": 0}],
                       "worsening": []}, sort_keys=True)
    (digest / "digest-20261001.jsonl").write_text(
        line + "\n", encoding="utf-8")
    payload = _tool_spend_forecast(ctx, {"digest_dir": str(digest)})
    assert payload["usable"] is False
