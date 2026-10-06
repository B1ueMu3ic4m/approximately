"""The help tour: 59 doors, seven topics, every door accounted for.

`approximately help` prints the topics; `approximately help
operations` prints that topic's doors with their one-liners. The
TOUR table is data, and test_v307 holds it to completeness: a
registered door with no tour entry fails the suite, so the tour
cannot rot behind the CLI.
"""

from __future__ import annotations

from typing import Dict, List

# topic -> (blurb, [(door, one-liner), ...])
TOUR: Dict[str, tuple] = {
    "record": ("capture agent runs and keep them trustworthy", [
        ("demo", "run the built-in failing agent (30s tour)"),
        ("new", "scaffold an instrumented agent project"),
        ("init", "wire the CI quality gate into this repo"),
        ("verify", "verify a trace's tamper-evident hash chain"),
        ("rotate", "re-key a signed trace"),
        ("doctor", "health check; --fix quarantines poison"),
        ("clean", "delete old traces (breach evidence survives)"),
        ("merge", "import another store's traces"),
        ("snapshot", "lossless whole-store backup"),
        ("restore", "verify and restore a snapshot"),
    ]),
    "understand": ("what a run did and why it failed", [
        ("report", "render the HTML postmortem"),
        ("attribute", "attribute a failure (MAST modes)"),
        ("explain", "explain a mode's detectors in prose"),
        ("diff", "git-style diff of two runs"),
        ("bisect", "first material divergence between two runs"),
        ("counterfactual", "do(step=empty) root-cause experiments"),
        ("repair", "minimal intervention set that clears attribution"),
        ("similar", "rank traces by alignment similarity"),
        ("cluster", "recidivist failure-mode statistics"),
        ("taxonomy", "the 14-mode MAST taxonomy"),
        ("query", "select traces with an expression"),
        ("dedupe", "collapse near-duplicate traces"),
        ("drift", "PSI behavior drift oldest vs newest"),
    ]),
    "operate": ("the on-call loop", [
        ("status", "one-glance ops overview"),
        ("tail", "one line per arrival, a scream per failure"),
        ("triage", "failed runs ranked by postmortem value"),
        ("grade", "letter grades for agents and tools"),
        ("handoff", "one markdown brief for the next engineer"),
        ("redact", "sanitized share-copy of a trace"),
        ("prices", "the store's price catalog"),
        ("annotate", "attach an analyst note"),
        ("annotations", "list annotations"),
        ("evidence", "one trace's complete case as a zip"),
        ("help", "the guided tour over all doors"),
    ]),
    "measure": ("trends, budgets and forecasts", [
        ("stats", "store statistics"),
        ("metrics", "store statistics (Prometheus with --prometheus)"),
        ("fleet", "aggregate stores into one dashboard"),
        ("anomalies", "robust latency/token anomalies"),
        ("curve", "context-curve measurement"),
        ("context", "token budget forecast for a trace"),
        ("budget", "replay a run against hypothetical rails"),
        ("predict", "failure-probability early warning"),
        ("optimize", "smallest context budget keeping recall"),
        ("calibrate", "temperature + conformal calibration"),
        ("compare", "baseline vs candidate store"),
        ("spool", "10s watch feeding the digest"),
    ]),
    "gate": ("fail the build when quality slips", [
        ("ci", "the quality gate: ceilings on rate/latency/spend"),
        ("audit", "composed nightly door with one exit code"),
        ("bench-gate", "performance wall as a CI gate"),
        ("benchmark", "run the benchmark corpus"),
        ("changelog", "generate CHANGELOG from docs/PLAN.md"),
    ]),
    "integrate": ("move data in and out", [
        ("mcp", "serve the toolkit over MCP (47 tools)"),
        ("export", "export traces to CSV/SARIF"),
        ("import", "import foreign transcripts"),
        ("export-dataset", "labeled benchmark JSONL out"),
        ("convert-mast", "MAST-Data annotations to JSONL"),
        ("distill", "distill the store into SFT/teacher data"),
        ("scan-tool", "scan a tool description for poisoning"),
    ]),
    "regress": ("turn failures into tests", [
        ("test", "generate a pytest regression file"),
        ("replay", "replay a trace through an executor"),
    ]),
}


def topics() -> List[str]:
    return list(TOUR)


def tour_entries() -> List[str]:
    """Every door named in the tour, in order."""
    return [door for _, doors in TOUR.values() for door, _ in doors]


def render_topic(topic: str) -> str:
    """One topic's doors; ValueError names the valid topics."""
    if topic not in TOUR:
        raise ValueError(
            f"unknown topic {topic!r} — topics: {', '.join(TOUR)}")
    blurb, doors = TOUR[topic]
    lines = [f"{topic} — {blurb}"]
    lines.extend(f"  {door:<14} {line}" for door, line in doors)
    return "\n".join(lines)


def render_index() -> str:
    lines = [("approximately — the operations-loop platform; "
              "topics: (approximately help TOPIC)")]
    lines.extend(f"  {name:<10} {blurb} ({len(doors)} doors)"
                 for name, (blurb, doors) in TOUR.items())
    return "\n".join(lines)
