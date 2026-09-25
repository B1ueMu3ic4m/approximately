"""Cross-store merge: import another store's traces, refusing broken evidence.

Fleet reality: teams run separate stores (per laptop, per CI runner,
per environment). `merge_store` unions a source store into a target
with three honest rules:

- **Broken evidence is refused, not imported.** Any source trace whose
  integrity block fails verification (TAMPERED, wrong-key) is reported
  and left behind — a merge must not become a tampering carrier.
- **Conflicts are explicit.** Same-id traces collide; the caller picks
  `skip` (keep target, default), `replace` (source wins), or `rename`
  (import under a `-m<n>` suffix).
- **Per-trace atomicity.** Imports go through the target store's atomic
  save, so an interrupted merge leaves the target intact.

Unsigned traces import normally (they carry no claims to verify); keyed
traces verify against the *keyed* rules — locked evidence imports,
forged evidence does not.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from .integrity import verify
from .store import TraceStore
from .trace import Trace

CONFLICT_POLICIES = ("skip", "replace", "rename")


@dataclass
class MergeReport:
    imported: List[str] = field(default_factory=list)
    annotations_carried: int = 0
    skipped_conflicts: List[str] = field(default_factory=list)
    refused_tampered: List[str] = field(default_factory=list)
    renamed: Dict[str, str] = field(default_factory=dict)

    @property
    def total_seen(self) -> int:
        return (len(self.imported) + len(self.skipped_conflicts)
                + len(self.refused_tampered))

    def summary(self) -> str:
        lines = [
            (f"merge: {len(self.imported)} imported, "
             f"{len(self.skipped_conflicts)} skipped (id conflict), "
             f"{len(self.refused_tampered)} refused (broken evidence)"),
        ]
        for old, new in self.renamed.items():
            lines.append(f"  renamed {old} -> {new}")
        lines.extend(f"  refused (integrity): {trace_id}"
                     for trace_id in self.refused_tampered)
        return "\n".join(lines)


def _check_evidence(trace: Trace) -> bool:
    """True when the trace carries no broken evidence claims."""
    if not trace.meta.get("integrity"):
        return True  # unsigned: nothing claimed, nothing to contradict
    return verify(trace).verdict in ("intact", "keyed")


def _rename_id(store: TraceStore, trace_id: str) -> str:
    suffix = 2
    candidate = f"{trace_id}-m{suffix}"
    while store.load(candidate) is not None:
        suffix += 1
        candidate = f"{trace_id}-m{suffix}"
    return candidate


def merge_store(source: Path, target: TraceStore,
                on_conflict: str = "skip") -> MergeReport:
    """Union the source store's traces into ``target``.

    Refuses traces whose integrity block fails verification, resolves
    id conflicts per ``on_conflict`` (skip/replace/rename), and saves
    through the target store's atomic write path.
    """
    if on_conflict not in CONFLICT_POLICIES:
        raise ValueError(f"on_conflict must be one of {CONFLICT_POLICIES}, "
                         f"got {on_conflict!r}")
    source_store = TraceStore(Path(source))
    if source_store.directory.resolve() == target.directory.resolve():
        raise ValueError("source and target store are the same directory")

    report = MergeReport()
    carried_notes = 0
    for trace in source_store.list_traces():
        if not _check_evidence(trace):
            report.refused_tampered.append(trace.id)
            continue
        if target.load(trace.id) is None:
            target.save(trace)
            report.imported.append(trace.id)
            continue
        if on_conflict == "skip":
            report.skipped_conflicts.append(trace.id)
        elif on_conflict == "replace":
            target.save(trace)
            report.imported.append(trace.id)
        else:  # rename
            old_id = trace.id
            new_id = _rename_id(target, old_id)
            trace.id = new_id
            target.save(trace)
            report.renamed[old_id] = new_id
            report.imported.append(new_id)
    # the annotation sidecar travels with the traces: notes about a
    # run belong to the run, wherever it lives. Re-anchored to the
    # (possibly renamed) trace id; append order preserved.
    source_notes = source_store.annotations()
    if source_notes:
        def _key(entry):
            # semantic identity: ts is wall-clock noise, content is not
            return json.dumps(
                {k: entry.get(k) for k in
                 ("trace_id", "author", "verdict", "note")},
                sort_keys=True)

        seen = {_key(e) for e in target.annotations()}
        for note in source_notes:
            entry = dict(note)
            entry["trace_id"] = report.renamed.get(entry["trace_id"],
                                                   entry["trace_id"])
            if _key(entry) in seen:
                continue
            target.annotate(entry["trace_id"], entry.get("note", ""),
                            author=entry.get("author", ""),
                            verdict=entry.get("verdict", ""))
            carried_notes += 1
    report.annotations_carried = carried_notes
    return report
