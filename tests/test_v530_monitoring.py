"""v530: the monitoring endpoint parses, the backup is honest,
the spend answers agree with the breaker.

The recorder/prices/forecast recon found the monitoring door
dead exactly when someone configured it: a --label composed
nested braces and double closing braces (a Prometheus scraper
drops the whole endpoint), None p95s rendered as literal None,
the snapshot of a nonexistent store was a valid zip with zero
traces and an exit 0, a non-zip restore tracebacked, the spend
doors and the breaker answered different dollars for the same
run, and an empty trend read "stable" — a verdict with no data.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

from approximately.budget import Budget, match_rate
from approximately.cluster import StoreStats
from approximately.metrics import render_prometheus, render_tool_prometheus
from approximately.report import trend_verdict

ROOT = Path(__file__).resolve().parent.parent


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "approximately", *args],
        capture_output=True, text=True, cwd=str(ROOT))


# ---- the monitoring endpoint parses under labels

def test_prometheus_labels_compose_with_one_brace():
    stats = StoreStats(traces=5, failures=2, avg_steps=3.0,
                       mode_counts={"FM-1.3": 1})
    out = render_prometheus(stats, extra_labels={"env": "prod"})
    assert 'approximately_mode_count{mode="FM-1.3",env="prod"}' in out
    assert "}}" not in out and "{{" not in out, \
        "a nested brace made the whole scrape unparseable"


def test_entity_labels_compose_and_none_p95_is_absent():
    rows = [{"tool": "search", "steps": 3, "errors": 0, "tokens": 50,
             "failed_traces": 0, "breached_traces": 0,
             "failure_rate": 0.0, "p95_ms": None,
             "p95_tokens": None}]
    out = render_tool_prometheus(rows, extra_labels={"env": "prod"})
    assert 'approximately_tool_p95_ms{tool="search",env="prod"}' \
        not in out, "no samples: absence, not a literal None"
    assert "}}" not in out and "None" not in out
    full = render_tool_prometheus([{**rows[0], "p95_ms": 12.0}])
    assert 'approximately_tool_p95_latency_ms{tool="search"} 12.0' \
        in full


def test_the_metrics_door_scrapes_clean_with_labels(tmp_path):
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    store = TraceStore(tmp_path)
    rec = Recorder("monitored", store=store)
    rec.tool("deploy", {"cmd": "x"}, result="boom")
    rec.respond("gave up", success=False)
    store.save(rec.trace)
    r = _run("--store", str(store.directory), "metrics",
             "--prometheus", "--by-agent", "--label", "env=prod")
    assert r.returncode == 0
    for line in r.stdout.splitlines():
        if line and not line.startswith("#"):
            assert line.count("{") == line.count("}"), line


# ---- the backup: honest about what it copied

def test_a_snapshot_of_a_missing_store_is_a_refusal(tmp_path):
    r = _run("--store", str(tmp_path / "typo-store"), "snapshot",
             str(tmp_path / "backup.zip"))
    assert r.returncode == 2,  (
        "the backup used to be a valid zip with zero traces and  "
        "an exit 0")
    assert "store not found" in r.stderr
    assert not (tmp_path / "backup.zip").exists()


def test_a_real_snapshot_still_works(tmp_path):
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    store = TraceStore(tmp_path / "s")
    rec = Recorder("snap task", store=store)
    rec.tool("sh", {"cmd": "x"}, result="ok")
    rec.respond("done", success=True)
    store.save(rec.trace)
    r = _run("--store", str(store.directory), "snapshot",
             str(tmp_path / "backup.zip"))
    assert r.returncode == 0 and "members" in r.stdout


def test_a_non_zip_restore_is_named_not_a_traceback(tmp_path):
    junk = tmp_path / "notazip.txt"
    junk.write_text("this is not a zip file", encoding="utf-8")
    r = _run("restore", str(junk), "--into", str(tmp_path / "d"))
    assert r.returncode == 2,  (
        "BadZipFile used to traceback (it is an OSError, not a  "
        "ValueError - the door caught only ValueError)")
    assert "Traceback" not in r.stderr


# ---- the spend doors agree with the breaker

def test_one_matcher_for_every_consumer():
    prices = {"gpt-4o": 0.5}
    assert match_rate(prices, "gpt-4o") == 0.5
    assert match_rate(prices, "openai/gpt-4o") == 0.5,  (
        "the breaker and the spend doors used to answer  "
        "differently for the same run")
    assert match_rate(prices, "GPT-4O") == 0.5
    assert match_rate(prices, "unknown-model") is None
    assert match_rate(prices, None) is None


def test_the_breaker_and_spend_agree(tmp_path):
    b = Budget(usd=10.0, prices={"gpt-4o": 0.5})
    b.charge(1_000_000, model="openai/gpt-4o")
    assert b.usd == 500.0 and b.exceeded_reasons() == ["usd"]
    from approximately.budget import match_rate

    # the spend door's own arithmetic over the same rate
    rate = match_rate({"gpt-4o": 0.5}, "openai/gpt-4o")
    assert round(1_000_000 / 1000 * rate, 4) == 500.0,  (
        "the spend doors used to report $0 unpriced while the  "
        "breaker charged $500")


def test_a_forgotten_rate_is_named(tmp_path):
    store = tmp_path / "s"
    store.mkdir()
    (store / "prices.json").write_text("{}", encoding="utf-8")
    r = _run("--store", str(store), "prices", "set", "gpt-4o")
    assert r.returncode == 2, \
        "float(None) is a TypeError - the door used to traceback"
    assert "rate must be a number" in r.stderr
    (store / "prices.json").write_text("{corrupt", encoding="utf-8")
    r = _run("--store", str(store), "prices", "unset", "gpt-4o")
    assert r.returncode == 2 and "Traceback" not in r.stderr


# ---- the forecast: chronology and honesty

def test_skewed_digest_days_cannot_invert_the_forecast(tmp_path):
    import datetime

    from approximately.fleet import trend_days

    digest_dir = tmp_path / "digests"
    digest_dir.mkdir()
    day = datetime.datetime(2026, 1, 5, 12, 0, 0)
    skew = datetime.datetime(2030, 6, 1, 12, 0, 0)
    lines = [
        json.dumps({"ts": skew.timestamp(),
                    "failures": 100, "traces": 120}),
        json.dumps({"ts": day.timestamp() + 3600,
                    "failures": 10, "traces": 120}),
    ]
    # the digest FILE is day-named (Windows forbids colons); the
    # skew lives in the ts field - exactly the hostile shape
    (digest_dir / f"digest-{day.date().isoformat()}.jsonl").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    days = trend_days(digest_dir)
    assert [d["day"] for d in days] == sorted(
        d["day"] for d in days), (
        "insertion order used to make the slope point backwards "
        "and the projection start in the past")


def test_an_empty_trend_is_no_data_not_stable():
    assert trend_verdict([]) == ("no data", 0.0),  (
        "an ops glance used to read 'no drift' where there was  "
        "nothing to measure")


def test_a_zero_failure_budget_is_refused(tmp_path):
    import datetime

    digest_dir = tmp_path / "digests"
    digest_dir.mkdir()
    day = datetime.date.today()
    lines = [json.dumps({"ts": time.time(),
                         "failures": 1, "traces": 10})]
    (digest_dir / f"digest-{day.isoformat()}.jsonl").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    r = _run("status", "--digest-dir", str(digest_dir),
             "--failure-budget", "0")
    assert r.returncode == 2,  (
        "a zero allowance used to answer 'exhausted: true' with  "
        "zero failures")
    assert "must be >= 1" in r.stderr


def test_the_recorder_slot_survives_an_out_of_order_exit():
    from approximately.recorder import Recorder, current_recorder

    a = Recorder("outer", save=False)
    b = Recorder("inner", save=False)
    a.__enter__()
    b.__enter__()
    a.__exit__(None, None, None)  # out of order: outer exits first
    assert current_recorder() is b,  (
        "the slot used to go None (every @agentstep inside b  "
        "recorded nothing) and later resurrect a finished recorder")
    b.__exit__(None, None, None)
    # after BOTH exits the LIFO contract is degenerate (b hands
    # the slot to the already-finished a) - out-of-order exits
    # are caller error; the fix is that b kept recording while
    # it was open
