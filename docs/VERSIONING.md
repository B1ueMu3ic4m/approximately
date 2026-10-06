# Versioning

The versioning standard, written down so the number means something.
This project follows [semver](https://semver.org/) — with its teeth
intact and its intent honored:

## Major (X.0.0) — capability milestones that carry a real contract change

A major is **not** a mood. It is shipped when both of these hold:

1. **A capability milestone**: the toolkit crossed a boundary in
   what it *is* — not a new door, a new wing. (v2 was the postmortem
   toolkit: record, attribute, replay, gate. v3 is the operations
   loop: live budget rails, the composed nightly audit, 47 MCP
   tools, and the on-call cycle — tail, triage, grade, handoff,
   snapshot, prices.)
2. **A real contract change**: something a user can observe break —
   a supported interpreter dropped, a CLI flag removed or
   re-defaulted, a store layout or wire format retired with a
   documented migration.

Both, together. A milestone without a contract change is a minor
with better marketing; a contract change without a milestone is a
minor with a migration note.

## Minor (3.X.0) — one feature batch

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
