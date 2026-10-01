"""v231: diff/bisect across stores — imported vs baseline.

The OTLP flow leaves imported traces in their own store; the healthy
reference run often lives elsewhere (a production baseline store).
`similar` had --other-store; diff and bisect get it too, so "what
diverged from the baseline?" works without merging stores first.
"""

import argparse
import json

from approximately.cli import cmd_bisect, cmd_diff
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed_both(tmp_path):
    failed_store = TraceStore(tmp_path / "imported")
    ok_store = TraceStore(tmp_path / "baseline")
    bad = Recorder("checkout fails on discount", save=False)
    bad.tool("cart", {"sku": "X"}, result="added")
    bad.tool("search", {"q": "discount code"}, result="no codes")
    bad.respond("gave up", success=False)
    failed_store.save(bad.trace)
    ok = Recorder("checkout works", save=False)
    ok.tool("cart", {"sku": "X"}, result="added")
    ok.tool("pay", {"amount": 10}, result="approved")
    ok.respond("done", success=True)
    ok_store.save(ok.trace)
    return (failed_store.list_traces()[0],
            ok_store.list_traces()[0])


def test_diff_across_stores(tmp_path, capsys):
    bad, ok = _seed_both(tmp_path)
    args = argparse.Namespace(store=str(tmp_path / "imported"),
                              trace=bad.id, other=ok.id,
                              other_store=str(tmp_path / "baseline"),
                              json=True)
    assert cmd_diff(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["a_id"] == bad.id
    assert payload["b_id"] == ok.id
    assert payload["similarity"] < 1.0


def test_bisect_across_stores(tmp_path, capsys):
    bad, ok = _seed_both(tmp_path)
    args = argparse.Namespace(store=str(tmp_path / "imported"),
                              trace=bad.id, other=ok.id,
                              other_store=str(tmp_path / "baseline"),
                              floor=0.8, json=True)
    assert cmd_bisect(args) == 0
    payload = json.loads(capsys.readouterr().out)
    # the first material divergence: the failed run searched for a
    # discount code where the baseline paid
    fault = payload["first_fault"]
    assert fault is not None
    assert fault["b_tool"] == "pay" or fault["a_tool"] == "search"


def test_same_store_still_works(tmp_path, capsys):
    bad, ok = _seed_both(tmp_path)
    store = TraceStore(tmp_path / "merged")
    store.save(bad)
    store.save(ok)
    args = argparse.Namespace(store=str(store.directory),
                              trace=bad.id, other=ok.id,
                              other_store=None, json=True)
    assert cmd_diff(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["a_id"] == bad.id
