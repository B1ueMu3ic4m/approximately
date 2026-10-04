"""Night VII, round 2: the reliability budget becomes standing.

``failure_budget`` joins the MCP surface (40 tools) and ``status``
gains ``--failure-budget`` — the allowance question is answerable by
agents and visible in the ops pulse, like the spend forecast before
it.  Validation mirrors the CLI door.
"""

import json

from approximately.cli import _status_payload, main
from approximately.mcp_server import (
    _TOOLS,
    ServerContext,
    _tool_failure_budget,
)
from approximately.store import TraceStore


def _digest(tmp_path, failures_by_day):
    import datetime
    digest = tmp_path / "d"
    digest.mkdir(parents=True, exist_ok=True)
    base = datetime.date(2026, 10, 1)
    for i, failures in enumerate(failures_by_day):
        stamp = (base + datetime.timedelta(days=i)).strftime("%Y%m%d")
        payload = {
            "ts": 1791000000 + i * 86400,
            "stores": [{"name": "s", "path": "/s", "traces": 10,
                        "failures": failures,
                        "failure_rate": failures / 10}],
            "worsening": []}
        (digest / f"digest-{stamp}.jsonl").write_text(
            json.dumps(payload, sort_keys=True) + "\n",
            encoding="utf-8")
    return digest


def test_tool_registered_with_schema():
    assert "failure_budget" in {t["name"] for t in _TOOLS}
    tool = next(t for t in _TOOLS if t["name"] == "failure_budget")
    assert tool["inputSchema"]["required"] == ["digest_dir",
                                               "allowance"]


def test_tool_reports_burn(tmp_path):
    digest = _digest(tmp_path, [2, 4])
    payload = _tool_failure_budget(ServerContext(str(tmp_path)),
                                   {"digest_dir": str(digest),
                                    "allowance": 10})
    assert payload["burned"] == 6
    assert payload["burn_fraction"] == 0.6
    assert len(payload["projection"]) == 14


def test_tool_refusals(tmp_path):
    digest = _digest(tmp_path, [1, 1])
    ctx = ServerContext(str(tmp_path))
    cases = [
        {"digest_dir": str(tmp_path / "nothing"), "allowance": 10},
        {"digest_dir": str(digest)},
        {"digest_dir": str(digest), "allowance": 0},
        {"digest_dir": str(digest), "allowance": -3},
        {"digest_dir": str(digest), "allowance": True},
        {"digest_dir": str(digest), "allowance": 10,
         "horizon_days": 0},
    ]
    for args in cases:
        try:
            _tool_failure_budget(ctx, args)
            raise AssertionError(f"no refusal for {args}")
        except KeyError:
            pass


def test_status_payload_carries_the_budget(tmp_path):
    from approximately.recorder import Recorder

    store = TraceStore(tmp_path / "s")
    with Recorder("calm", model="m/1", store=store) as rec:
        rec.respond("done", success=True)
    digest = _digest(tmp_path, [2, 4])
    payload = _status_payload(store, store.list_traces(), digest,
                              failure_allowance=10)
    assert payload["failure_budget"]["burned"] == 6
    payload = _status_payload(store, store.list_traces(), digest)
    assert "failure_budget" not in payload


def test_status_prose_names_the_burn(tmp_path, capsys):
    from approximately.recorder import Recorder as R
    store = TraceStore(tmp_path / "s")
    with R("calm", model="m/1", store=store) as rec:
        rec.respond("done", success=True)
    digest = _digest(tmp_path, [9, 9])
    rc = main(["status", "--store", str(store.directory),
               "--digest-dir", str(digest), "--failure-budget", "10"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "failure budget: 18/10 failed runs (EXHAUSTED)" in out


def test_cli_flag_round_trips(tmp_path, capsys):
    from approximately.recorder import Recorder as R
    store = TraceStore(tmp_path / "s")
    with R("calm", model="m/1", store=store) as rec:
        rec.respond("done", success=True)
    digest = _digest(tmp_path, [2, 4])
    rc = main(["status", "--store", str(store.directory),
               "--digest-dir", str(digest), "--failure-budget", "10",
               "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["failure_budget"]["burn_fraction"] == 0.6
