"""Night VII, round 5: what fills the window.

``context <trace> --composition`` breaks a run's context down by
step kind — estimated tokens, share, and each kind's worst
contributor.  The answer to "why is my window full?" when the
answer is not the model: a run whose context is 80% tool results
has a truncation problem, not a context-length problem.
"""

import json

from approximately.cli import main
from approximately.context import composition
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _mixed_run(tmp_path):
    store = TraceStore(tmp_path / "s")
    with Recorder("the full run", model="m/1", store=store,
                  save=False) as rec:
        rec.plan("search, compare, book")
        rec.tool("search", {"q": "SFO"}, result="x" * 8_000)
        rec.tool("compare", {"a": 1}, result="y" * 2_000)
        rec.respond("booked", success=True)
    store.save(rec.trace)
    return store, rec.trace


def test_composition_shares_sum_to_one(tmp_path):
    _, trace = _mixed_run(tmp_path)
    payload = composition(trace)
    assert payload["total_tokens"] > 0
    assert abs(sum(p["share"] for p in payload["parts"]) - 1.0) < 0.01


def test_tool_results_dominate_the_window(tmp_path):
    _, trace = _mixed_run(tmp_path)
    payload = composition(trace)
    by_kind = {p["kind"]: p for p in payload["parts"]}
    assert by_kind["tool_call"]["share"] > 0.5
    # the 8k-char search result is the single worst contributor
    assert by_kind["tool_call"]["worst_step"] == 1


def test_kinds_sorted_by_share(tmp_path):
    _, trace = _mixed_run(tmp_path)
    shares = [p["share"] for p in composition(trace)["parts"]]
    assert shares == sorted(shares, reverse=True)


def test_composition_never_counts_empty_steps(tmp_path):
    store = TraceStore(tmp_path / "s")
    with Recorder("empty", model="m/1", store=store,
                  save=False) as rec:
        rec.tool("silent", {})
        rec.respond("done", success=True)
    payload = composition(rec.trace)
    # a result-less, arg-less tool call contributes nothing
    assert all(p["kind"] != "tool_call" or p["tokens"] > 0
               for p in payload["parts"])


def test_cli_door_prose_and_json(tmp_path, capsys):
    store, trace = _mixed_run(tmp_path)
    rc = main(["context", trace.id, "--store", str(store.directory),
               "--composition"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "context composition of" in out
    assert "tool_call" in out

    rc = main(["context", trace.id, "--store", str(store.directory),
               "--composition", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["parts"][0]["kind"] == "tool_call"
