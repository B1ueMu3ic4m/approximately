#!/usr/bin/env python3
"""Regenerate the HTML artifacts shown in the README.

Runs the built-in demo scenarios into a throwaway store and renders
the real deliverables into docs/artifacts/ - the same pages users get
from `report --all`, `curve`, and `fleet`. Re-run after changing any
renderer:

    python3 scripts/make_docs_artifacts.py
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs" / "artifacts"


def main() -> int:
    DOCS.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        store = str(Path(tmp) / "store")
        subprocess.run([sys.executable, "-m", "approximately.cli",
                        "demo", "--store", store], check=True)
        subprocess.run([sys.executable, "-m", "approximately.cli",
                        "--store", store, "report", "--all",
                        "--output", DOCS / "index.html"], check=True)
        subprocess.run([sys.executable, "-m", "approximately.cli",
                        "--store", store, "curve", "latest",
                        "--output", DOCS / "curve.html"], check=True)
        # the single-run postmortem page the index links to
        import shutil

        reports = sorted(Path(store).glob("*.report.html"))
        if reports:
            shutil.copy(reports[-1], DOCS / "report.html")
        subprocess.run([sys.executable, "-m", "approximately.cli",
                        "fleet", store, "--fleet-html",
                        DOCS / "fleet.html"], check=True)
        # the MAST leaderboard the README links to
        root = Path(__file__).resolve().parent.parent
        subprocess.run([sys.executable, "-m", "approximately.cli",
                        "benchmark", str(root / "docs"
                                         / "mast-bench-multi.jsonl"),
                        "--multi-label", "--html",
                        str(DOCS / "leaderboard.html")], check=True)
    print(f"artifacts written to {DOCS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
