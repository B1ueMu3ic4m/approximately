"""Multi-agent demo: a researcher/writer crew that fails the classic ways.

Deterministic, no API key. Showcases the multi-agent recording conventions
(``Recorder.message``) and the detectors for FM-2.4 (information
withholding) and FM-3.1 (premature termination).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

from .attributor import attribute
from .recorder import Recorder
from .store import TraceStore
from .trace import Trace


def _run_crew(rec: Recorder) -> None:
    rec.plan("Researcher gathers findings; writer publishes the brief.",
             agent="orchestrator")
    rec.tool("web_search",
             {"query": "context window cost studies"},
             result="3 studies found; the 2026 token-cost analysis is key",
             thought="gather sources for the brief",
             agent="researcher")
    # FM-2.4: the researcher flags findings for the writer but never sends
    # them, and the writer drafts anyway (on stale state).
    rec.tool("summarize_sources",
             {"ids": [1, 2, 3]},
             result="findings: token cost rises superlinearly past 32k",
             agent="researcher",
             share_with=["writer"])
    rec.tool("write_draft",
             {"topic": "token costs"},
             result="draft v1 written (without the findings)",
             agent="writer")
    # FM-3.1: the run ends while the brief was never reviewed or published.
    rec.respond("Draft v1 written.", success=False, agent="orchestrator")


def run_demo(store_dir: Optional[Path] = None) -> Tuple[Trace, object,
                                                        Optional[Path]]:
    store = TraceStore(store_dir) if store_dir else TraceStore()
    with Recorder(
        "Research token-cost studies and publish a brief (researcher + writer).",
        model="demo/research-writer-crew",
        store=store,
    ) as rec:
        _run_crew(rec)

    report = attribute(rec.trace)
    path = store.directory / f"{rec.trace.id}.report.html"
    from .report import render_html

    path.write_text(render_html(rec.trace, report), encoding="utf-8")
    return rec.trace, report, path

