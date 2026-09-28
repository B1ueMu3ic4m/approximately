"""v161: the glance can fail a pipeline.

Cron wrappers need exit codes, not prose. `status
--fail-on-anomalies` exits 1 when fleet latency outliers exist;
`--fail-on-worsening` exits 1 when the trend verdict says the store
is getting worse (needs `--digest-dir`). The frame still prints
first — the alert explains itself.
"""

import argparse
import json

from approximately.cli import cmd_status
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed(directory, slow=False):
    store = TraceStore(directory)
    for i in range(4):
        rec = Recorder(f"boring {i}", save=False)
        rec.tool("search", {"q": str(i)}, result="hit")
        rec.respond("done", success=True)
        rec.trace.steps[0].latency_ms = (1800, 2000, 2100, 1900)[i]
        store.save(rec.trace)
    if slow:
        rec = Recorder("the slow one", save=False)
        rec.tool("search", {"q": "heavy"}, result="hit")
        rec.respond("done", success=True)
        rec.trace.steps[0].latency_ms = 30000
        store.save(rec.trace)
    return store


def test_fail_on_anomalies_exits_one(tmp_path, capsys):
    _seed(tmp_path / "s", slow=True)
    args = argparse.Namespace(store=str(tmp_path / "s"), since=None,
                              digest_dir=None, json=True,
                              watch=False, interval=30.0, frames=None,
                              fail_on_anomalies=True,
                              fail_on_worsening=False)
    rc = cmd_status(args)
    payload = json.loads(capsys.readouterr().out)
    assert payload["fleet_anomalies"]["count"] == 1
    assert rc == 1


def test_quiet_store_passes(tmp_path, capsys):
    _seed(tmp_path / "s", slow=False)
    args = argparse.Namespace(store=str(tmp_path / "s"), since=None,
                              digest_dir=None, json=True,
                              watch=False, interval=30.0, frames=None,
                              fail_on_anomalies=True,
                              fail_on_worsening=False)
    assert cmd_status(args) == 0


def test_fail_on_worsening_requires_trend(tmp_path, capsys):
    _seed(tmp_path / "s", slow=False)
    args = argparse.Namespace(store=str(tmp_path / "s"), since=None,
                              digest_dir=None, json=False,
                              watch=False, interval=30.0, frames=None,
                              fail_on_anomalies=False,
                              fail_on_worsening=True)
    # no digest_dir -> no trend -> no verdict -> pass
    assert cmd_status(args) == 0
    assert "fleet trend" not in capsys.readouterr().out


def test_worsening_trend_fails(tmp_path, capsys, monkeypatch):
    _seed(tmp_path / "s", slow=False)
    # a digest history whose verdict is worsening
    from approximately import cli as cli_mod

    class FakeTrend:
        verdict = "worsening"

    def fake_summarize(days):
        return FakeTrend()

    monkeypatch.setattr(cli_mod, "_status_payload",
                        lambda store, traces, digest_dir, since=None:
                        {"store": "fake", "traces": 1,
                         "failures": 0,
                         "failure_rate": 0.0, "top_modes": {},
                         "annotations": 0, "annotations_confirmed": 0,
                         "last_failure": None, "trend":
                         {"verdict": "worsening"},
                         "ledger_intact": None,
                         "top_recidivist": None,
                         "fleet_anomalies": {"count": 0,
                                             "worst": None},
                         "triage_coverage": {"annotated_failures": 0,
                                             "failures": 0,
                                             "ratio": None}})
    args = argparse.Namespace(store=str(tmp_path / "s"), since=None,
                              digest_dir=str(tmp_path / "d"),
                              json=False, watch=False,
                              interval=30.0, frames=None,
                              fail_on_anomalies=False,
                              fail_on_worsening=True)
    assert cmd_status(args) == 1
    assert "--fail-on-worsening" in capsys.readouterr().err
