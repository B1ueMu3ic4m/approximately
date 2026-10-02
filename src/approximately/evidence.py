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


def build_evidence_pack(store, trace_id: str, output: Path,
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

    manifest: Dict[str, Any] = {
        "pack_version": 1,
        "trace_id": trace.id,
        "task": trace.task,
        "created_at": trace.created_at,
        "verdict": report.primary_mode.id,
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
        for name, data in (
                ("trace.json", json.dumps(trace.to_dict(),
                                          default=str,
                                          indent=2) + "\n"),
                ("report.html", render_html(trace, report,
                                            store=store)),
                ("annotations.json", json.dumps(annotations,
                                                default=str,
                                                indent=2) + "\n")):
            payload = data.encode("utf-8")
            zf.writestr(name, payload)
            hashed[name] = hashlib.sha256(payload).hexdigest()
        # the manifest hashes every member but itself — a reviewer
        # recomputes the list from the members and compares
        manifest["members"] = hashed
        zf.writestr("manifest.json", json.dumps(
            manifest, indent=2, sort_keys=True) + "\n")
    return manifest
