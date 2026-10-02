"""v246: the watch does not cry wolf.

An alarm that rings every cycle is an alarm storm — on-call learns
to ignore it exactly when it matters.  `fleet --watch --webhook`
gains a cooldown: the SAME set of alert reasons re-pages only after
`--alert-cooldown` minutes; a reason set that GROWS (a new store
degraded, a new gate tripped) pages immediately.  Digest snapshots
still write every cycle — the cooldown gates the PAGER, never the
record.
"""

from pathlib import Path

from approximately.fleet import _alert_reasons, watch_fleet
from approximately.recorder import Recorder
from approximately.store import TraceStore


class _Spy:
    def __init__(self):
        self.calls = []

    def __call__(self, summaries, url, **kw):
        self.calls.append(len(self.calls))
        return "200"


def _burn_store(path):
    from approximately.trace import Step, Trace

    store = TraceStore(path)
    trace = Trace(task="loopy run", id="loopy", created_at=1.0)
    for tokens in (110, 95, 105, 90, 100, 115, 85, 120, 108, 92):
        trace.add(Step(kind="tool_call", tool="search",
                       tokens=tokens, latency_ms=40))
    trace.add(Step(kind="tool_call", tool="search", tokens=9000,
                   latency_ms=40))
    trace.add(Step(kind="response", result="done"))
    store.save(trace)
    return store


def _steady_store(path):
    store = TraceStore(path)
    rec = Recorder("calm", store=store, save=False)
    rec.respond("done", success=True)
    return store


def test_alert_reasons_keys_per_store_and_cause():
    burn = _burn_store(Path("/tmp/unused-burn"))
    steady = _steady_store(Path("/tmp/unused-calm"))
    from approximately.fleet import survey

    summaries = survey([burn.directory, steady.directory])
    reasons = _alert_reasons(summaries, None, None, 1, None)
    assert any(r.endswith(":tokens") for r in reasons)
    assert all("calm" not in r for r in reasons)


def test_cooldown_silences_the_same_alarm():
    burn = _burn_store(Path("/tmp/unused-b2"))
    spy = _Spy()
    # no thresholds: every cycle is alert-worthy; cooldown must
    # still collapse identical alarms
    watch_fleet([burn.directory], Path("/tmp/unused-d1"), 0.0,
                iterations=5, webhook_url="http://x/", notify=spy,
                alert_cooldown=3600.0, clock=lambda: 0.0)
    assert len(spy.calls) == 1


def test_growth_semantics_and_default_unchanged():
    from approximately.fleet import survey

    burn = _burn_store(Path("/tmp/unused-b3"))
    steady = _steady_store(Path("/tmp/unused-c3"))
    burn_reasons = _alert_reasons(
        survey([burn.directory]), 0.0, None, 1, None)
    steady_reasons = _alert_reasons(
        survey([steady.directory]), 0.0, None, 1, None)
    # burn is a strict superset: adding the burn store GROWS the
    # set, which is what earns an immediate re-page
    assert burn_reasons > steady_reasons or (
        burn_reasons and not burn_reasons <= steady_reasons)

    # cooldown 0 = the old behavior: every cycle pages
    spy = _Spy()
    watch_fleet([burn.directory], Path("/tmp/unused-d2"), 0.0,
                iterations=3, webhook_url="http://x/", notify=spy,
                alert_cooldown=0.0, clock=lambda: 0.0)
    assert len(spy.calls) == 3


def test_cooldown_lapse_repages():
    burn = _burn_store(Path("/tmp/unused-b4"))
    spy = _Spy()
    ticks = iter(range(0, 10_000, 10))
    watch_fleet([burn.directory], Path("/tmp/unused-d3"), 0.0,
                iterations=4, webhook_url="http://x/", notify=spy,
                alert_cooldown=15.0, clock=lambda: next(ticks))
    # t=0 pages, t=10 inside cooldown, t=20 lapsed pages, t=30 inside
    assert len(spy.calls) == 2


def test_digest_writes_every_cycle_even_while_silent(tmp_path):

    burn = _burn_store(tmp_path / "burn")
    digest = tmp_path / "digest"
    spy = _Spy()
    watch_fleet([burn.directory], digest, 0.0, iterations=4,
                webhook_url="http://x/", notify=spy,
                alert_cooldown=3600.0, clock=lambda: 0.0)
    days = list(digest.glob("digest-*.jsonl"))
    assert days and \
        sum(1 for _ in days[0].read_text(
            encoding="utf-8").splitlines()) == 4
    assert len(spy.calls) == 1
