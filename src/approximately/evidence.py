"""Evidence packs: one trace's complete case in a single archive.

`approximately evidence <trace>` writes a zip with everything a
reviewer needs to judge a run without touching the store: the
native record (integrity chain embedded), the HTML postmortem, the
trace's annotations, an on-the-spot verification verdict, and a
manifest that names the sha256 of every member — so the pack
itself is tamper-evident.  Deterministic member order; no store
paths leak into the archive.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional


def _handoff_brief(trace: Any, store: Any) -> Optional[str]:
    """The one-page markdown brief, when the handoff door can
    render one — a pack carries its own executive summary. A brief
    failure (poison step, foreign record) shrinks the pack instead
    of failing it."""
    try:
        from .handoff import brief

        return brief(trace, store)
    except Exception:
        return None


def _agent_grade(trace: Any, store: Any) -> Optional[dict]:
    """The failed run's primary agent's current letter grade — a
    reviewer sees at a glance whether this case is a pattern or a
    fluke. n/a grades pass through honestly; an error never fails
    the pack."""
    try:
        from .cluster import agent_scorecard
        from .grade import grade_card

        cards = agent_scorecard(store.list_traces())
        agents = [s.agent for s in trace.steps if s.agent]
        if not agents:
            return None
        card = next((c for c in cards
                     if c.get("agent") == agents[0]), None)
        if card is None:
            return None
        row = grade_card(card)
        return {"agent": row["subject"], "grade": row["grade"]}
    except Exception:
        return None


def build_evidence_pack(store: Any, trace_id: str, output: Path,
                        key: Optional[bytes] = None) -> Dict[str, Any]:
    """Write the evidence pack for *trace_id*; returns the manifest.

    Raises ``ValueError`` when the trace id is unknown — a pack is
    never an empty archive with a shrug.
    """
    trace = store.load(trace_id)
    if trace is None:
        raise ValueError(f"no such trace: {trace_id}")
    from .attributor import attribute
    from .integrity import verify
    from .report import render_html

    report = attribute(trace)
    chain = verify(trace, key=key)
    annotations = []
    try:
        annotations = [a for a in store.annotations()
                       if str(a.get("trace_id")) == trace.id]
    except Exception:
        annotations = []

    agent_grade = _agent_grade(trace, store)
    manifest: Dict[str, Any] = {
        "pack_version": 1,
        "trace_id": trace.id,
        "task": trace.task,
        "created_at": trace.created_at,
        "verdict": report.primary_mode.id,
        "agent_grade": agent_grade,
        "chain": {
            "signed": chain.signed,
            "intact": chain.intact,
            "verdict": chain.verdict_override or (
                "intact" if chain.intact else "tampered"),
            "detail": chain.detail,
        },
        "members": {},
        "packed_at": datetime.datetime.now(
            datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    with zipfile.ZipFile(output, "w",
                         compression=zipfile.ZIP_DEFLATED) as zf:
        hashed = {}
        brief = _handoff_brief(trace, store)
        members = [
            ("trace.json", json.dumps(trace.to_dict(),
                                      default=str,
                                      indent=2) + "\n"),
            ("report.html", render_html(trace, report,
                                        store=store)),
            ("annotations.json", json.dumps(annotations,
                                            default=str,
                                            indent=2) + "\n"),
        ]
        if brief is not None:
            members.append(("brief.md", brief + "\n"))
        for name, data in members:
            payload = data.encode("utf-8")
            zf.writestr(name, payload)
            hashed[name] = hashlib.sha256(payload).hexdigest()
        # the manifest hashes every member but itself — a reviewer
        # recomputes the list from the members and compares
        manifest["members"] = hashed
        zf.writestr("manifest.json", json.dumps(
            manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def build_store_packs(store: Any, out_dir: Path,
                      key: Optional[bytes] = None) -> Dict[str, Any]:
    """Pack every trace in the store; write an index over them.

    The archive scenario: a store leaving the machine (offboarding,
    a compliance pull) becomes one directory of per-trace packs
    plus an ``index.json`` naming each pack and its chain verdict.
    Empty stores raise — an archive of nothing is a mistake.
    """
    from .store import stamped_breach

    traces = store.list_traces()
    if not traces:
        raise ValueError("store is empty: no runs to pack")
    out_dir.mkdir(parents=True, exist_ok=True)
    index = []
    for trace in traces:
        pack_path = out_dir / f"{trace.id}.evidence.zip"
        manifest = build_evidence_pack(store, trace.id, pack_path,
                                       key=key)
        index.append({
            "trace_id": trace.id,
            "task": trace.task,
            "verdict": manifest["verdict"],
            "chain": manifest["chain"]["verdict"],
            "budget_breached": stamped_breach(trace.meta),
            "pack": pack_path.name,
            "sha256": hashlib.sha256(pack_path.read_bytes())
                      .hexdigest(),
        })
    index_path = out_dir / "index.json"
    index_path.write_text(json.dumps({
        "packs": len(index),
        "packed_at": datetime.datetime.now(
            datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "traces": index,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"packs": len(index), "index": str(index_path),
            "traces": index}


def verify_evidence_pack(pack: Path,
                         key: Optional[bytes] = None) -> Dict[str, Any]:
    """The reviewer's side: recompute every manifest hash, then
    verify the chain inside the extracted record.  A missing or
    altered member fails loudly; an unsigned record reports
    unsigned (the pack's manifest still matching means it arrived
    intact — the chain says whether what arrived is trustworthy).
    """
    with zipfile.ZipFile(pack) as zf:
        names = set(zf.namelist())
        if "manifest.json" not in names:
            raise ValueError("not an evidence pack: no manifest")
        manifest = json.loads(zf.read("manifest.json"))
        recorded = manifest.get("members") or {}
        mismatched = [name for name, digest in recorded.items()
                      if name not in names
                      or hashlib.sha256(zf.read(name)).hexdigest()
                      != digest]
        missing = sorted(set(recorded) - names)
        record = None
        if "trace.json" in names:
            from .trace import Trace

            record = Trace.from_dict(
                json.loads(zf.read("trace.json")))
    chain = None
    if record is not None:
        from .integrity import verify

        result = verify(record, key=key)
        chain = {
            "signed": result.signed,
            "intact": result.intact,
            "verdict": result.verdict_override or (
                "intact" if result.intact else "tampered"),
            "detail": result.detail,
        }
    return {
        "pack": str(pack),
        "trace_id": manifest.get("trace_id"),
        "members_checked": len(recorded),
        "mismatched": mismatched,
        "missing": missing,
        "manifest_ok": not mismatched and not missing,
        "chain": chain,
    }
