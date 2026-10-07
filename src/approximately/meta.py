"""Repository metadata as code.

The GitHub About line and topic list are pinned here so the repo's
public face cannot drift from the shipped surface: the suite asserts
the one-liner fits GitHub's 350-character budget, quotes the real MCP
tool count, and that every topic obeys GitHub's topic grammar. After
editing either, sync the live repo::

    gh repo edit --description "$(python - <<'PY'
    from approximately.meta import ABOUT; print(ABOUT)
    PY
    )"
    gh repo edit --add-topic mcp   # keep topics in step with meta.TOPICS
"""

from __future__ import annotations

import re

ABOUT = (
    "Flight recorder, MAST failure attribution & on-call ops loop for AI "
    "agents: replay, tamper-evident evidence, triage queue, letter grades, "
    "handoff briefs, fleet tail, price catalog. 48 MCP tools. Zero "
    "dependencies, Python 3.10+."
)

TOPICS: tuple[str, ...] = (
    "ai-agents",
    "agent-observability",
    "autogen",
    "benchmark",
    "conformal-prediction",
    "context-engineering",
    "crewai",
    "debugging",
    "distillation",
    "drift-detection",
    "llamaindex",
    "llm",
    "llm-ops",
    "mast",
    "mcp",
    "openai-agents",
    "postmortem",
    "replay-testing",
    "sre",
)

_TOPIC_RE = re.compile(r"^[a-z0-9-]+$")
_TOOL_COUNT_RE = re.compile(r"(\d+) MCP tools")


def tool_count_claim() -> int | None:
    """The MCP tool count quoted inside ABOUT, or None if unquoted."""
    m = _TOOL_COUNT_RE.search(ABOUT)
    return int(m.group(1)) if m else None
