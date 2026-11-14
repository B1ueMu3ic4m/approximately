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
        # the manifest hashes every member but itself; with a key
        # it is also SIGNED (v5.0.0: the unsigned manifest made the
        # pack's tamper-evidence advisory — a re-stamped member
        # with a recomputed digest verified TRUSTED, and dropping
        # members from the manifest de-covered them silently)
        manifest["members"] = hashed
        if key is not None:
            import hmac as _hmac

            manifest["signature"] = _hmac.new(
                key, _canonical_manifest(manifest),
                hashlib.sha256).hexdigest()
        zf.writestr("manifest.json", json.dumps(
            manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def _canonical_manifest(manifest: dict) -> bytes:
    body = {k: v for k, v in manifest.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, default=str).encode("utf-8")


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
        from .store import safe_artifact

        pack_path = safe_artifact(out_dir, trace.id,
                                  ".evidence.zip")
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


def _check_manifest(zf: "zipfile.ZipFile", names: set,
                    manifest: dict,
                    key: Optional[bytes]) -> dict:
    """The manifest audit, both directions and the signature:
    manifest->members (each digest matches its member), members->manifest
    (nothing rides outside the fence), and the HMAC — a signed pack
    with no key is locked (saying TRUSTED would be the de-coverage
    attack winning by omission), an unsigned pack under a
    key-holding reviewer is advisory and named."""
    import hmac as _hmac

    recorded = manifest.get("members") or {}
    signature = manifest.get("signature")
    manifest.pop("signature", None)
    mismatched = [name for name, digest in recorded.items()
                  if name not in names
                  or hashlib.sha256(zf.read(name)).hexdigest()
                  != digest]
    missing = sorted(set(recorded) - names)
    uncovered = sorted(names - set(recorded) - {"manifest.json"})
    signature_ok = None
    if signature is not None:
        signature_ok = _hmac.compare_digest(
            signature, _hmac.new(
                key or b"", _canonical_manifest(manifest),
                hashlib.sha256).hexdigest())
        if key is None:
            signature_ok = False
    elif key is not None:
        signature_ok = False
    return {"recorded": recorded, "mismatched": mismatched,
            "missing": missing, "uncovered": uncovered,
            "signed": signature is not None,
            "signature_ok": signature_ok}


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
        checked = _check_manifest(zf, names, manifest, key)
        recorded = checked["recorded"]
        mismatched = checked["mismatched"]
        missing = checked["missing"]
        uncovered = checked["uncovered"]
        signature_ok = checked["signature_ok"]
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
        "uncovered": uncovered,
        "manifest_signed": checked["signed"],
        "signature_ok": signature_ok,
        "manifest_ok": (not mismatched and not missing
                        and not uncovered
                        and signature_ok is not False),
        "chain": chain,
    }
