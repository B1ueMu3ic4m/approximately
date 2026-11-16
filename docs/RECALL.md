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

# 5. take the memory with you (one markdown diary)
approximately recall --export diary.md
```

## What each door answers

| Door | Answers | Notes |
|---|---|---|
| `recall` | The timeline: conversations in the order they happened, grouped by day | `--grep TEXT` turns it into a search that shows the excerpt of the moment something was said |
| `recall-summary` | Day by day: how many conversations, top topics, which tools carried them, how many failed | CJK-aware topics (bigrams), no dependencies |
| `--export FILE` | The whole memory as one markdown diary (summary + timeline) | written atomically |

## Filters (they all compose)

- `--since` / `--until` — a unix epoch or a human duration (`30m`,
  `2h`, `1d`, `1w`)
- `--day YYYY-MM-DD` — one calendar day: the drill-down step from
  the summary's day rows; a real date with nothing on it reads as
  an honest empty answer, garbage is refused at the flag boundary
- `--model NAME` — case-insensitive substring over the recorded model
- `--failed-only` / `--ok-only` — the outcome filters
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
