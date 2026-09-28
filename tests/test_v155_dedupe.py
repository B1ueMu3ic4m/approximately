"""v155: dedupe — near-duplicate traces, one command.

`import` deduplicates exactly (deterministic ids); `dedupe` catches
the *almost* identical runs: same task, same steps, seconds apart —
the retries and cron double-fires that quietly pollute a dataset
before a fine-tuning export. Single-pass clustering keeps it O(n·k);
MCP tool #29 `find_duplicates` mirrors it.
"""

import argparse
import json

from approximately.align import duplicate_groups, similarity
from approximately.cli import cmd_dedupe
from approximately.mcp_server import ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed(directory, twin_count=2):
    store = TraceStore(directory)
    ids = []
    for _ in range(twin_count):
        rec = Recorder("book a flight to Oslo", save=False)
        rec.tool("search", {"q": "oslo flights"}, result="3 hits")
        rec.respond("booked", success=True)
        store.save(rec.trace)
        ids.append(rec.trace.id)
    odd = Recorder("water the plants", save=False)
    odd.respond("done", success=True)
    store.save(odd.trace)
    return store, ids


def test_duplicate_groups_found(tmp_path):
    store, ids = _seed(tmp_path / "s")
    groups = duplicate_groups(store.list_traces())
    assert len(groups) == 1
    assert groups[0]["size"] == 2
    assert sorted(groups[0]["ids"]) == sorted(ids)
    assert groups[0]["task"] == "book a flight to Oslo"


def test_distinct_traces_form_no_groups(tmp_path):
    store, _ = _seed(tmp_path / "s", twin_count=1)
    assert duplicate_groups(store.list_traces()) == []


def test_threshold_strictness(tmp_path):
    store = TraceStore(tmp_path / "s")
    base = Recorder("deploy and verify", save=False)
    base.tool("deploy", {"env": "prod"}, result="ok")
    base.respond("done", success=True)
    store.save(base.trace)
    cousin = Recorder("deploy and verify", save=False)
    cousin.tool("deploy", {"env": "prod"}, result="ok")
    cousin.tool("verify", {"url": "/health"}, result="green")
    cousin.respond("done", success=True)
    store.save(cousin.trace)
    # an extra verify step drops alignment to 0.25: a strict floor
    # never clusters it, and no floor in (0.25, 1) can either unless
    # the runs truly align
    strict = duplicate_groups(store.list_traces(), threshold=0.99)
    assert strict == []
    assert similarity(store.list_traces()[0],
                      store.list_traces()[1]) < 0.5


def test_cli_dedupe_json(tmp_path, capsys):
    store, _ids = _seed(tmp_path / "s")
    args = argparse.Namespace(store=str(store.directory),
                              threshold=0.95, max_traces=2000,
                              json=True)
    assert cmd_dedupe(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["redundant_traces"] == 1
    assert len(payload["groups"]) == 1


def test_mcp_find_duplicates(tmp_path):
    store, _ = _seed(tmp_path / "s")
    ctx = ServerContext(str(store.directory))
    payload = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "find_duplicates",
                   "arguments": {"store": str(store.directory)}},
    }, ctx)
    result = json.loads(payload["result"]["content"][0]["text"])
    assert result["redundant_traces"] == 1
    assert result["groups"][0]["size"] == 2
