"""v81: per-agent fleet trend — digests carry top agents, and
`fleet --trend --agent NAME` plots one agent's touched-fail rate over
days with the Theil-Sen verdict and the worsening gate.

Honest limitation, pinned here: a snapshot stores each store's TOP-3
busiest named agents, so a day's zero row means "not observed", not
"perfect". Corrupt digest lines stay skipped (v0.40 semantics).
"""

import json

from approximately.cli import build_parser
from approximately.fleet import agent_trend_days, digest_snapshot, survey
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _digest_dir(tmp_path, rate_by_day):
    digests = tmp_path / "digests"
    for day, rate in enumerate(rate_by_day, 1):
        day_ts = 86400 * 20000 + 43200 + day * 86400
        for snap_i in range(2):
            digests.mkdir(parents=True, exist_ok=True)
            (digests / f"digest-{20260900 + day}.jsonl").open("a").write(
                json.dumps({
                    "ts": day_ts + snap_i,
                    "worsening": [],
                    "stores": [{
                        "name": "s", "path": "/tmp/s",
                        "traces": 10, "failure_rate": rate,
                        "trend_verdict": "stable", "trend_slope": 0.0,
                        "worsening": False, "ledger_intact": None,
                        "top_modes": [],
                        "top_agents": [{
                            "agent": "worker", "steps": 10 + snap_i,
                            "tool_calls": 8, "errors": (rate and 1) or 0,
                            "tokens": 100, "traces": 10,
                            "failed_traces": round(rate * 10),
                            "failure_rate": rate,
                        }],
                    }],
                }, sort_keys=True) + "\n")
    return digests


def test_agent_trend_days_aggregates_per_day(tmp_path):
    digests = _digest_dir(tmp_path, [0.1, 0.5, 0.9])
    rows = agent_trend_days(digests, "worker")
    assert [r["day"] for r in rows] == ["2024-10-05", "2024-10-06",
                                        "2024-10-07"]
    # last snapshot of each day wins; steps come from snap_i=1
    assert rows[0]["steps"] == 11
    assert rows[2]["failed_traces"] == 9 and rows[2]["traces"] == 10


def test_agent_trend_missing_agent_reads_as_unobserved(tmp_path):
    digests = _digest_dir(tmp_path, [0.1, 0.5])
    rows = agent_trend_days(digests, "nobody")
    assert all(r["steps"] == 0 and r["traces"] == 0 for r in rows)


def test_agent_trend_survives_corrupt_lines(tmp_path):
    digests = _digest_dir(tmp_path, [0.2])
    with (digests / "digest-20260901.jsonl").open("a") as fh:
        fh.write("{torn line\n")
    rows = agent_trend_days(digests, "worker")
    assert len(rows) == 1 and rows[0]["traces"] == 10


def test_cli_agent_trend_json_and_table(tmp_path, capsys):
    digests = _digest_dir(tmp_path, [0.1, 0.5, 0.9])
    parser = build_parser()
    args = parser.parse_args(["fleet", str(tmp_path / "unused"), "--trend", "--agent",
                              "worker", "--digest-dir", str(digests),
                              "--json"])
    assert args.func(args) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["agent"] == "worker" and len(body["days"]) == 3

    args = parser.parse_args(["fleet", str(tmp_path / "unused"), "--trend", "--agent",
                              "worker", "--digest-dir", str(digests)])
    assert args.func(args) == 0
    out = capsys.readouterr().out
    assert "agent trend - worker" in out
    assert "2024-10-07" in out
    assert "verdict" in out


def test_cli_agent_trend_worsening_gate(tmp_path, capsys):
    digests = _digest_dir(tmp_path, [0.0, 0.4, 0.9])
    parser = build_parser()
    args = parser.parse_args(["fleet", str(tmp_path / "unused"), "--trend", "--agent",
                              "worker", "--digest-dir", str(digests),
                              "--fail-on-worsening"])
    assert args.func(args) == 1
    assert "worsening" in capsys.readouterr().err


def test_digest_snapshot_from_real_survey_carries_top_agents(tmp_path):
    store = TraceStore(str(tmp_path / "s"))
    rec = Recorder("crew", save=False)
    rec.tool("bash", {"cmd": "x"}, result="y", agent="worker")
    rec.respond("done", success=False, agent="worker")
    store.save(rec.trace)
    snap = digest_snapshot(survey([store.directory]))
    assert snap["stores"][0]["top_agents"][0]["agent"] == "worker"
