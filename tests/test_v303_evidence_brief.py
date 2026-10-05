"""v303: the evidence pack carries its own executive summary.

``brief.md`` rides in the zip: the handoff door's one-page brief
rendered at pack time, hashed into the manifest like every other
member. A pack is the case file a human receives — it should open
with the summary. A brief failure (poison step, foreign record)
shrinks the pack instead of failing it.
"""

import zipfile

from approximately.evidence import build_evidence_pack
from approximately.recorder import Recorder
from approximately.store import TraceStore


def test_pack_carries_brief(tmp_path):
    store = TraceStore(tmp_path)
    with Recorder("the incident", store=store) as rec:
        rec.tool("sh", {"cmd": "deploy"}, result="ok")
        rec.fail("boom")
    out = tmp_path / "case.zip"
    manifest = build_evidence_pack(store, rec.trace.id, out)
    assert "brief.md" in manifest["members"]
    with zipfile.ZipFile(out) as zf:
        brief = zf.read("brief.md").decode("utf-8")
        names = set(zf.namelist())
    assert "# Handoff:" in brief and "## What failed" in brief
    assert "the incident" in brief
    assert names == {"trace.json", "report.html", "annotations.json",
                     "brief.md", "manifest.json"}


def test_brief_failure_shrinks_the_pack(tmp_path, monkeypatch):
    store = TraceStore(tmp_path)
    with Recorder("odd case", store=store) as rec:
        rec.tool("sh", {"cmd": "x"}, result="ok")
        rec.fail("boom")
    import approximately.handoff as handoff

    def boom(trace, store):
        raise RuntimeError("poison step")

    monkeypatch.setattr(handoff, "brief", boom)
    out = tmp_path / "case.zip"
    manifest = build_evidence_pack(store, rec.trace.id, out)
    assert "brief.md" not in manifest["members"]
    with zipfile.ZipFile(out) as zf:
        assert "brief.md" not in zf.namelist()
    assert set(manifest["members"]) == {"trace.json", "report.html",
                                        "annotations.json"}


def test_brief_is_hashed_like_every_member(tmp_path):
    import hashlib

    store = TraceStore(tmp_path)
    with Recorder("hashed case", store=store) as rec:
        rec.tool("sh", {"cmd": "x"}, result="ok")
        rec.fail("boom")
    out = tmp_path / "case.zip"
    manifest = build_evidence_pack(store, rec.trace.id, out)
    with zipfile.ZipFile(out) as zf:
        actual = hashlib.sha256(zf.read("brief.md")).hexdigest()
    assert manifest["members"]["brief.md"] == actual
