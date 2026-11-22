# Conversation memory — finding what you talked about with the AI

Long conversations evaporate: weeks later nobody remembers what was
asked, what was decided, or where that one solution lived. The
store already records every run faithfully — `recall` turns it back
into memory: a chronological timeline, a search that finds the
moment something was said, and a day-by-day summary. Zero
dependencies; nothing leaves the machine.

## The loop

```
# 1. what did I even talk about last week?
approximately recall --since 1w

# 2. where was that discussion about backoff retries?
approximately recall --grep "backoff"

# 3. what did Tuesday look like, day by day?
approximately recall-summary --since 1w

# 4. drill into that one day the summary flagged
approximately recall --day 2026-11-17

# 5. the weekly postmortem: day rows + the failed runs,
#    with error excerpts and the failure modes the detectors name
approximately recall-digest --since 1w

# 6. take the memory with you (one markdown diary)
approximately recall --export diary.md
approximately recall-digest --since 1w --export digest.md
```

## What each door answers

| Door | Answers | Notes |
|---|---|---|
| `recall` | The timeline: conversations in the order they happened, grouped by day | `--grep TEXT` turns it into a search that shows the excerpt of the moment something was said |
| `recall-summary` | Day by day: how many conversations, top topics, which tools carried them, how many failed | CJK-aware topics (bigrams), no dependencies |
| `recall-digest` | The weekly postmortem: the day rows PLUS every failed run — its error excerpt (the moment it broke) and the failure modes the rule detectors name; modes recurring across 2+ days are named as the pattern | `--export digest.md` files it atomically |
| `recall --related ID` | From one conversation, the related ones — scored by shared tools (a Jaccard), shared task topics, and the same day; each result names the reasons its score was earned | deterministic: equal scores break by trace id |
| `--export FILE` | The whole memory as one markdown diary (summary + timeline) | written atomically |

## Filters (they all compose)

- `--since` / `--until` — a unix epoch or a human duration (`30m`,
  `2h`, `1d`, `1w`)
- `--day YYYY-MM-DD` — one calendar day: the drill-down step from
  the summary's day rows; a real date with nothing on it reads as
  an honest empty answer, garbage is refused at the flag boundary
- `--model NAME` — case-insensitive substring over the recorded model
- `--failed-only` / `--ok-only` — the outcome filters
- `--query EXPR` — the shared query DSL over every conversation:
  any field the expression language knows (`success`, `mode`,
  `tools`, `failed_tools`, `max_latency`, `tokens`, `created` with
  time words …), e.g. `recall --query "success == false and
  created > 24h ago"`; a malformed expression is refused by name
- `--utc` — bucket days in UTC instead of the machine's zone:
  two operators in different timezones read the same store the
  same way (the default stays the human's own zone)
- `--limit N` — the newest N conversations (the search cap is 20)
- `--json` — machine-readable shapes for scripts and MCP clients

## One memory across several stores

Conversations live wherever each agent ran. Positional store paths
read as ONE memory:

```
approximately recall ~/agents/ops-store ~/agents/coding-store
```

- the timeline interleaves across stores (still chronological) and
  every entry names its store
- the same trace id landing in two boxes counts once (the first
  store wins)
- if the two copies carry DIFFERENT content, the id is named as
  **diverged** — two boxes holding two histories of one
  conversation is exactly the sync-conflict the evidence ledger
  exists to catch, so it is never silently read away
- the summary's day rows name the stores that carried them, and
  the `--export` diary lists the fleet in its header
- a typo'd store path answers `store not found` — a silently
  created empty store would read as lost memory

## Conflicts in a fleet view

When several stores are read as one memory, a trace id appearing
in two boxes counts once — but if the two copies carry DIFFERENT
content, the id is named as **diverged** in the timeline, the
summary, the digest and the exports: two boxes holding two
histories of one conversation is exactly the sync-conflict the
evidence ledger exists to catch, so it is never silently read
away. Identical copies stay one memory, no noise.

## MCP

The same doors are MCP tools (`recall`, with `grep`, `summarize`,
`since_days`, `day`, `limit`, `stores`), so an agent can answer
"what did we do about X last week?" from inside the conversation —
which is where the question usually comes from.

## What memory is made of

Every `Recorder` run is a conversation: the task line, each tool
call with its result, thought, and error, and the final output.
The searcher walks every field a conversation speaks through
(`task`, `result`, `thought`, `error`, `final_output`) and shows
a readable window around the match — the moment it was said, not
the whole log. Records are stored with tamper-evident chains
(`verify`), so the memory you are reading is the memory that was
recorded.

## Triage annotations

Reading the memory ends with a verdict. Annotations live in an
append-only sidecar (`annotations.jsonl`), and each one is
chain-stamped — keyed HMAC when a signing key is in play, plain
sha256 when not — so an edited verdict or a removed line breaks
every later link:

```
approximately annotate TRACE_ID "looks like the deploy timeout family" \
    --verdict confirmed
approximately verify --annotations          # the triage-log verdict
approximately verify --annotations A B     # fleet: exit is the worst
```

`verify --annotations` names every broken link by line and trace;
legacy unsigned lines never read as broken; a keyed entry whose
key has rotated is unverifiable (cannot judge without the key)
but its link continuity is still auditable. `doctor --deep` walks
the chain and fails the health verdict on any broken link —
verdicts drive triage, so a broken chain is broken evidence.

`recall --related TRACE_ID` reads the same verdicts: two
conversations the analyst confirmed the SAME way earn a
`same verdict` reason and lead the results.

`recall --export` carries each conversation's latest verdict onto
its timeline line (`· triage: confirmed "looks like…"`), and the
diary closes with a `## Triage` tally: how many failed
conversations carry a verdict, which words, how many still
unannotated.
