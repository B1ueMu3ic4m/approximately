"""Store snapshot & restore: lossless backup with tamper evidence.

``evidence --all`` curates per-trace case packs for sharing; a
snapshot is the other need — move or back up the *whole store*
without loss. Every member is hashed into a ``manifest.json`` inside
the zip; ``restore`` recomputes each hash before extracting, so a
corrupted or doctored archive refuses rather than silently restoring
poison. Locks, temp files and ZCode droppings are not evidence and
do not travel.
"""

from __future__ import annotations

import hashlib
import json
import time
import zipfile
from pathlib import Path
from typing import List, Tuple

from .prices import STORE_ARTIFACTS

MANIFEST_NAME = "manifest.json"
SNAPSHOT_FORMAT = 1

_SKIP_SUFFIXES = (".lock", ".tmp")


def _member_candidates(store_dir: Path) -> List[Path]:
    """Everything in the store that is evidence: root trace JSONs and
    artifacts, the annotation and ledger sidecars, quarantined bytes
    (preserved evidence), never locks or temp files."""
    out: List[Path] = []
    for path in sorted(store_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(store_dir)
        if path.suffix in _SKIP_SUFFIXES:
            continue
        if rel.parent.name == ".quarantine" or \
                path.name.endswith(".jsonl") or \
                path.name in STORE_ARTIFACTS or \
                (rel.parent == Path(".") and path.suffix == ".json"):
            out.append(path)
    return out


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot(store_dir: Path, out_path: Path) -> dict:
    """Zip the store with a sha256 manifest; returns the report."""
    store_dir = Path(store_dir)
    out_path = Path(out_path)
    members = _member_candidates(store_dir)
    # zip member names are POSIX by spec (zipfile normalizes
    # os.sep on write) - the manifest keys must match or Windows
    # verification fails against its own archive
    table = {m.relative_to(store_dir).as_posix(): _sha256(m)
             for m in members}
    manifest = {
        "format": SNAPSHOT_FORMAT,
        "store": str(store_dir),
        "created_at": time.time(),
        "members": table,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w",
                         compression=zipfile.ZIP_DEFLATED) as zf:
        for m in members:
            zf.write(m, arcname=m.relative_to(store_dir).as_posix())
        zf.writestr(MANIFEST_NAME,
                    json.dumps(manifest, indent=2, sort_keys=True))
    return {
        "store": str(store_dir),
        "snapshot": str(out_path),
        "members": len(table),
        "manifest_sha256": _sha256(out_path),
    }


def _load_manifest(zf: zipfile.ZipFile, archive: Path) -> dict:
    try:
        raw = zf.read(MANIFEST_NAME)
    except KeyError:
        raise ValueError(
            f"{archive}: no {MANIFEST_NAME} inside — not a snapshot"
        ) from None
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"{archive}: corrupt manifest: {exc}") from None
    if not isinstance(manifest, dict) or \
            not isinstance(manifest.get("members"), dict):
        raise ValueError(f"{archive}: manifest has no member table")
    return manifest


def verify_snapshot(archive: Path) -> Tuple[dict, List[str]]:
    """Recompute every member hash; returns (manifest, offenders).

    An empty offender list means the archive is exactly what the
    manifest recorded."""
    archive = Path(archive)
    if not archive.is_file():
        raise ValueError(f"no such snapshot: {archive}")
    with zipfile.ZipFile(archive) as zf:
        manifest = _load_manifest(zf, archive)
        offenders = []
        for name, recorded in manifest["members"].items():
            try:
                data = zf.read(name)
            except KeyError:
                offenders.append(f"{name}: missing from archive")
                continue
            actual = hashlib.sha256(data).hexdigest()
            if actual != recorded:
                offenders.append(f"{name}: sha256 mismatch")
        offenders.extend(
            f"{name}: not in manifest"
            for name in zf.namelist()
            if name != MANIFEST_NAME
            and name not in manifest["members"])
    return manifest, offenders


def restore(archive: Path, into: Path, force: bool = False) -> dict:
    """Verify, then extract into ``into``; refuses on any hash
    mismatch (listing offenders) or on existing files without
    ``force`` — a restore that overwrites silently is how backups
    lose trust."""
    archive = Path(archive)
    into = Path(into)
    manifest, offenders = verify_snapshot(archive)
    if offenders:
        raise ValueError("snapshot verification failed: "
                         + "; ".join(offenders[:5])
                         + (f" (+{len(offenders) - 5} more)"
                            if len(offenders) > 5 else ""))
    clashes = [name for name in manifest["members"]
               if (into / name).exists()]
    if clashes and not force:
        raise ValueError(
            f"{len(clashes)} file(s) already exist in {into} "
            f"(first: {clashes[0]}) — pass --force to overwrite")
    into.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        for name in manifest["members"]:
            target = into / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(name))
    return {
        "snapshot": str(archive),
        "restored_into": str(into),
        "members": len(manifest["members"]),
        "original_store": manifest.get("store"),
        "created_at": manifest.get("created_at"),
    }
