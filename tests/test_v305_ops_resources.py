"""v305: the browsable ops surface — v3.3.0.

MCP clients can now browse the operations state without tool calls:
`grades`, `triage` and `prices.json` appear as resources beside the
traces (a corrupt catalog surfaces honestly as a resource). And the
evidence pack's manifest carries the failed run's primary agent's
current letter grade — a reviewer sees pattern-vs-fluke at a glance.
"""

import json
from pathlib import Path

from approximately.evidence import build_evidence_pack
from approximately.mcp_server import ServerContext, _resources, _resources_read
from approximately.prices import set_rate
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed(tmp_path):
    store = TraceStore(tmp_path)
    for i in range(5):
        with Recorder(f"run {i}", store=store) as rec:
            rec.tool("sh", {}, agent="bot",
                     result="ok" if i < 3 else "x",
                     error=None if i < 3 else "boom")
            if i >= 3:
                rec.fail("boom")
    set_rate(tmp_path, "m", 1.0)
    return store


def _read(tmp_path, tail, rid=1):
    return json.loads(_resources_read(
        {"params": {"uri": f"approximately://{tmp_path}/{tail}"}},
        ServerContext(str(tmp_path)), rid)["result"]["contents"][0]["text"])


def test_ops_resources_registered(tmp_path):
    _seed(tmp_path)
    uris = [r["uri"] for r in _resources(ServerContext(str(tmp_path)))]
    assert any(u.endswith("/grades") for u in uris)
    assert any(u.endswith("/triage") for u in uris)
    assert any(u.endswith("/prices.json") for u in uris)


def test_grades_resource(tmp_path):
    _seed(tmp_path)
    payload = _read(tmp_path, "grades")
    assert payload["kind"] == "agent"
    assert any(g["subject"] == "bot" for g in payload["grades"])


def test_triage_resource(tmp_path):
    _seed(tmp_path)
    payload = _read(tmp_path, "triage")
    assert payload["total"] == 2
    assert {"novelty", "cost", "blast", "recency"} == \
        set(payload["queue"][0]["parts"])


def test_prices_resource_clean_and_corrupt(tmp_path):
    _seed(tmp_path)
    assert _read(tmp_path, "prices.json")["prices"] == {"m": 1.0}
    (Path(tmp_path) / "prices.json").write_text("{bad",
                                                encoding="utf-8")
    corrupt = _read(tmp_path, "prices.json")
    assert corrupt["corrupt"] is True and "detail" in corrupt


def test_unknown_resource_still_refuses(tmp_path):
    _seed(tmp_path)
    uri = f"approximately://{tmp_path}/nope"
    resp = _resources_read({"params": {"uri": uri}},
                           ServerContext(str(tmp_path)), 9)
    assert resp["error"]["code"] == -32602


def test_evidence_pack_carries_agent_grade(tmp_path):
    store = _seed(tmp_path)
    failing = next(t.id for t in store.list_traces()
                   if t.success is False and t.task == "run 4")
    out = tmp_path / "case.zip"
    manifest = build_evidence_pack(store, failing, out)
    assert manifest["agent_grade"]["agent"] == "bot"
    # D reliability (2/5) x0.5 + A budget x0.25 + D discipline x0.25
    # = 1.75 points -> F: a 40% failure rate is a pattern, not a fluke
    assert manifest["agent_grade"]["grade"] == "F"
