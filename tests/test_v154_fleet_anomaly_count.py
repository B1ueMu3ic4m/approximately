"""v154: the fleet survey counts slow spots per store.

`fleet` (and the MCP `survey` mirror, and every webhook payload) now
carries `fleet_anomalies` — the store-wide per-tool outlier count —
plus the worst offender, so a multi-project sweep answers "which
store is quietly slow" without visiting each one.
"""

import json

from approximately.fleet import survey, webhook_payload
from approximately.mcp_server import ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed(directory):
    store = TraceStore(directory)
    jitter = (1800, 2000, 2100, 1900)
    for i in range(4):
        rec = Recorder(f"boring {i}", save=False)
        rec.tool("search", {"q": str(i)}, result="hit")
        rec.respond("done", success=True)
        rec.trace.steps[0].latency_ms = jitter[i]
        store.save(rec.trace)
    slow = Recorder("the slow one", save=False)
    slow.tool("search", {"q": "heavy"}, result="hit")
    slow.respond("done", success=True)
    slow.trace.steps[0].latency_ms = 30000
    store.save(slow.trace)
    return store


def test_survey_row_counts_anomalies(tmp_path):
    _seed(tmp_path / "slow-store")
    calm = TraceStore(tmp_path / "calm")
    rec = Recorder("calm run", save=False)
    rec.respond("done", success=True)
    calm.save(rec.trace)
    summaries = survey([tmp_path / "slow-store", tmp_path / "calm"])
    by_name = {s.name: s for s in summaries}
    assert by_name["slow-store"].fleet_anomalies == 1
    assert by_name["slow-store"].worst_anomaly["tool"] == "search"
    assert by_name["calm"].fleet_anomalies == 0
    assert by_name["calm"].worst_anomaly is None


def test_webhook_payload_includes_anomalies(tmp_path):
    _seed(tmp_path / "s")
    payload = webhook_payload(survey([tmp_path / "s"]))
    row = payload["stores"][0]
    assert row["fleet_anomalies"] == 1
    assert row["worst_anomaly"]["latency_ms"] == 30000


def test_mcp_survey_mirror_includes_anomalies(tmp_path):
    _seed(tmp_path / "s")
    ctx = ServerContext(".")
    payload = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "survey",
                   "arguments": {"stores": [str(tmp_path / "s")]}},
    }, ctx)
    result = json.loads(payload["result"]["content"][0]["text"])
    assert result["stores"][0]["fleet_anomalies"] == 1


def test_fleet_prose_names_slow_outliers(tmp_path, capsys):
    from approximately.cli import _print_fleet

    _seed(tmp_path / "s")
    summaries = survey([tmp_path / "s"])
    _print_fleet(summaries)
    out = capsys.readouterr().out
    assert "1 slow outlier(s)" in out
