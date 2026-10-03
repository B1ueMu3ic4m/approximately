"""Night VI, round 5: the breaker's receipt in the postmortem.

A Budget breach (v2.70.0) already stops the run, stamps the trace,
gates the pipeline (v2.71.0), pages the fleet (v2.72.0) and survives
housekeeping (v2.73.0) — but the HTML postmortem never said WHY a run
died mid-episode.  The budget card closes that loop: what the rails
metered, what the ceilings were, and whether the breaker tripped.
"""


from approximately.attributor import attribute
from approximately.budget import Budget
from approximately.evidence import build_evidence_pack, verify_evidence_pack
from approximately.integrity import sign
from approximately.recorder import Recorder
from approximately.report import render_html
from approximately.store import TraceStore


def _burned_trace():
    budget = Budget(tokens=10_000, usd=0.05, prices={"m/1": 0.01})
    with Recorder("burn task", model="m/1", save=False,
                  budget=budget) as rec:
        rec.tool("cheap", tokens=4_000)
        rec.tool("pricey", tokens=12_000)
    return rec.trace


def _calm_trace():
    budget = Budget(tokens=50_000, usd=1.0, prices={"m/1": 0.01})
    with Recorder("calm task", model="m/1", save=False,
                  budget=budget) as rec:
        rec.tool("only", tokens=1_000)
        rec.respond("done", success=True)
    return rec.trace


def test_breached_report_shows_the_verdict():
    html = render_html(_burned_trace(), attribute(_burned_trace()))
    assert "Live budget" in html
    assert "BREACHED" in html
    assert "16,000" in html
    assert "ceiling 10,000" in html
    assert "ceiling $0.05" in html


def test_under_budget_report_still_shows_the_meters():
    html = render_html(_calm_trace(), attribute(_calm_trace()))
    assert "Live budget" in html
    assert "within budget" in html
    assert "BREACHED" not in html
    assert "1,000" in html


def test_no_rails_no_card():
    with Recorder("plain", save=False) as rec:
        rec.tool("t", tokens=9)
        rec.respond("done", success=True)
    html = render_html(rec.trace, attribute(rec.trace))
    assert "Live budget" not in html


def test_poison_budget_meta_never_breaks_the_report():
    with Recorder("poisoned", save=False) as rec:
        rec.tool("t", tokens=9)
        rec.trace.meta = "not a dict"
    html = render_html(rec.trace, attribute(rec.trace))
    assert "Live budget" not in html


def test_unpriced_tokens_surface_in_the_card():
    budget = Budget(usd=1.0, prices={"m/other": 0.01})
    with Recorder("mystery", model="m/unknown", save=False,
                  budget=budget) as rec:
        rec.tool("t", tokens=4_000)
    html = render_html(rec.trace, attribute(rec.trace))
    assert "unpriced" in html
    assert "4,000 tok" in html


def test_evidence_pack_carries_the_card_and_stays_trusted(tmp_path):
    trace = _burned_trace()
    sign(trace, key=b"night-vi-r5")
    store = TraceStore(tmp_path / "store")
    store.save(trace)
    pack_path = tmp_path / "case.zip"
    build_evidence_pack(store, trace.id, pack_path, key=b"night-vi-r5")
    verdict = verify_evidence_pack(pack_path, key=b"night-vi-r5")
    assert verdict["manifest_ok"] is True
    assert verdict["mismatched"] == [] and verdict["missing"] == []
    assert verdict["chain"]["signed"] is True
    assert verdict["chain"]["intact"] is True
    import zipfile
    with zipfile.ZipFile(pack_path) as z:
        report = z.read("report.html").decode("utf-8")
    assert "BREACHED" in report
    assert "ceiling 10,000" in report
