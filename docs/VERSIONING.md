# Versioning

The versioning standard, written down so the number means something.
This project follows [semver](https://semver.org/) — with its teeth
intact and its intent honored:

## Major (X.0.0) — capability milestones that carry a real contract change

A major is **not** a mood. It is shipped when both of these hold:

1. **A capability milestone**: the toolkit crossed a boundary in
   what it *is* — not a new door, a new wing. (v2 was the postmortem
   toolkit: record, attribute, replay, gate. v3 is the operations
   loop: live budget rails, the composed nightly audit, 50 MCP
   tools, and the on-call cycle — tail, triage, grade, handoff,
   snapshot, prices.)
2. **A real contract change**: something a user can observe break —
   a supported interpreter dropped, a CLI flag removed or
   re-defaulted, a store layout or wire format retired with a
   documented migration.

Both, together. A milestone without a contract change is a minor
with better marketing; a contract change without a milestone is a
minor with a migration note.

## The single-digit minor (the rule)

**MINOR never reaches 10.** A minor is one digit, 0–9, and the
ninth minor of a major line is the last: further batches ride
patches until the major rolls. The 3.x line broke this rule —
its minor raced to 99 on per-round bumps — and the drift is
reclassified below. From v4.0.0 the rule is enforced by policy:
if a ninth minor is full, the next batch is either a patch or
the conversation about the next major.

## Minor (X.Y.0) — one feature batch

A minor is shipped **per batch, not per commit**. A night's work
that lands three doors is one minor, not three; the CHANGELOG entry
names all three. Minor numbers measure batches of user-facing
capability, and no number-pumping.

## Patch (3.X.Y) — fixes and docs

Bug fixes, perf-budget work, doc releases, CI hygiene. No new
user-facing doors.

## The ledger

`docs/PLAN.md` is the single source of truth; `CHANGELOG.md` is
generated newest-first from it, and the newest entry always tracks
`pyproject.toml`'s version (docs-health test enforces this).
Version gaps (a number skipped by a squash merge) are recorded in
the neighboring entry and are not re-used.

## The 3.x reclassification (v4.0.0)

The historical line, regrouped honestly:

| Era | Versions | What it was |
|---|---|---|
| Birth | 0.x | the recorder and the first analysis doors |
| Instrumented analysis | 1.x | attribution, benchmarks, the MAST ladder |
| The ops loop | 2.x | fleet, digest, watch, prediction, prices |
| The channel begins | 3.0–3.9 | signed webhook, the MCP server, evidence transport |
| The drift (reclassified) | 3.10–3.99 | the channel maturing into a full ops loop — ~90 minors that were batches-then-patches under the old per-round habit; **reclassified as the tail of the 3.x channel era**, not ninety features |
| The discipline | **4.0.0** | the versioning rule itself (single-digit minor) plus the toolkit as a complete agent-ops loop: 52 MCP tools, 66 doors, and a signed channel with sender identity, chain gating, batch plans, a retry spool and a rate cap |

Two promises hold:

1. **History is never rewritten.** Every tag and release from
   0.1.0 to 3.99.1 stays exactly as published — tags are
   artifacts of the record, and a project whose product is a
   tamper-evident ledger does not get to re-tag its own past.
   The reclassification lives in this document and the ledger,
   not in force-pushed history.
2. **The number means something again.** After 3.99.1 the major
   is a boundary, the minor is one digit, and the patch is the
   routine beat.
