"""v5947: the related scorer reads the human verdicts.

Shared tools, shared topics and the same day are behavioral
signals; the strongest relatedness signal there is — the analyst
already looked at both runs and called them the SAME thing — was
invisible to the scorer. ``related`` now reads the annotation
sidecar once (the same pass the diary uses): two conversations
carrying the SAME triage verdict earn a "same verdict" reason and
a score bump, the candidate's verdict word rides its result entry
(``"verdict": "confirmed"``), and an unannotated candidate never
earns the reason. The ordering stays deterministic (score desc,
then id); the fleet view works unchanged — the triage map already
aggregates across boxes.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "approximately", *args],
        capture_output=True, text=True, cwd=str(ROOT),
        encoding="utf-8")


def _seed(tmp_path):
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    store = TraceStore(tmp_path / "s")
    for task, tool in (("payments timeout run", "deploy"),
                       ("payments docs review", "deploy"),
                       ("unrelated garden", "garden_hose")):
        rec = Recorder(task, save=False)
        rec.tool(tool, {}, result=None, error="boom")
        rec.respond("done", success=False)
        store.save(rec.trace)
    ids = {t.task: t.id for t in store.list_traces()}
    store.annotate(ids["payments timeout run"], "the deploy family",
                   verdict="confirmed")
    store.annotate(ids["payments docs review"], "sibling review",
                   verdict="confirmed")
    store.annotate(ids["unrelated garden"], "different call",
                   verdict="false-positive")
    return store, ids


def test_the_same_verdict_leads_and_names_itself(tmp_path):
    store, ids = _seed(tmp_path)
    r = _run("--store", str(store.directory), "recall", "--related",
             ids["payments timeout run"], "--json")
    payload = _payload(r)
    top = payload["results"][0]
    assert top["task"] == "payments docs review", \
        "the verdict-matched sibling leads"
    assert "same verdict" in top["reasons"], \
        "the human signal is named as a reason"
    assert top["verdict"] == "confirmed", \
        "the candidate's verdict word rides its entry"
    assert all("same verdict" not in r["reasons"]
               for r in payload["results"][1:]), \
        "an unannotated candidate never earns the reason"


def _payload(response):
    import json
    return json.loads(response.stdout)


def test_a_clashing_verdict_does_not_earn_it(tmp_path):
    store, ids = _seed(tmp_path)
    r = _run("--store", str(store.directory), "recall", "--related",
             ids["unrelated garden"], "--json")
    payload = _payload(r)
    siblings = [x for x in payload["results"]
                if x["task"] == "payments docs review"]
    if siblings:
        assert "same verdict" not in siblings[0]["reasons"], \
            "confirmed vs false-positive is not the same verdict"


def test_the_fleet_scoring_works_unchanged(tmp_path):
    from approximately.recall import MultiStore, related
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    for name, task in (("a", "ship the payments flow"),
                       ("b", "review the payments docs")):
        store = TraceStore(tmp_path / name)
        rec = Recorder(task, save=False)
        rec.tool("deploy", {}, result="ok")
        rec.respond("done", success=True)
        store.save(rec.trace)
    view = MultiStore()
    view.add(TraceStore(tmp_path / "a"), str(tmp_path / "a"))
    view.add(TraceStore(tmp_path / "b"), str(tmp_path / "b"))
    box_b = TraceStore(tmp_path / "b")
    box_b.annotate(box_b.list_traces()[0].id, "same family",
                  verdict="confirmed")
    target_id = TraceStore(tmp_path / "a").list_traces()[0].id
    TraceStore(tmp_path / "a").annotate(target_id, "target",
                                       verdict="confirmed")
    payload = related(view, target_id, limit=5)
    assert payload["related"] == 1
    top = payload["results"][0]
    assert top["store"] == "b"
    assert "same verdict" in top["reasons"], \
        "a cross-box verdict match still earns the reason"
