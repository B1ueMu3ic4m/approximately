"""MAST failure taxonomy: the 14 failure modes behind Approximately's attribution.

Encoding of the taxonomy from Cemri et al., "Why Do Multi-Agent LLM Systems
Fail?" (arXiv:2503.13657), annotated with published distribution numbers and
engineering fixes backed by the paper's intervention experiments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Failure categories (MAST "Failure Categories")
FC1 = "FC1"
FC2 = "FC2"
FC3 = "FC3"

CATEGORY_NAMES = {
    FC1: "Specification & System Design Issues",
    FC2: "Inter-Agent Misalignment",
    FC3: "Task Verification",
}

# Published share of failures per category (MAST, 1600+ annotated traces).
CATEGORY_SHARE = {FC1: 41.77, FC2: 36.94, FC3: 21.30}


@dataclass
class FailureMode:
    """One MAST failure mode with an engineering fix list."""

    id: str                    # e.g. "FM-1.3"
    category: str              # FC1 / FC2 / FC3
    name: str                  # short human name
    definition: str            # what it looks like in a trace
    fixes: List[str] = field(default_factory=list)
    mast_share: Optional[float] = None  # % of traces showing this mode in MAST

    @property
    def category_name(self) -> str:
        return CATEGORY_NAMES[self.category]

    @property
    def label(self) -> str:
        return f"{self.id} {self.name}"


def _fm(
    id: str,
    category: str,
    name: str,
    definition: str,
    fixes: List[str],
    share: Optional[float] = None,
) -> FailureMode:
    return FailureMode(id=id, category=category, name=name,
                       definition=definition, fixes=fixes, mast_share=share)


FAILURE_MODES: Dict[str, FailureMode] = {
    m.id: m
    for m in [
        _fm("FM-1.1", FC1, "Disobey Task Specification",
            "The agent violates explicit constraints or requirements of the task.",
            ["Restate task constraints in the system prompt as a checklist.",
             "Add a post-run spec validator that rejects outputs violating constraints.",
             "Convert prohibitions into tool-level policy (do not expose the forbidden tool)."]),
        _fm("FM-1.2", FC1, "Disobey Role Specification",
            "An agent acts outside the responsibilities of its assigned role.",
            ["Add explicit role boundaries with an explicit 'you must not' list (MAST intervention: +9.4%).",
             "Route out-of-role requests to a coordinator instead of acting."]),
        _fm("FM-1.3", FC1, "Step Repetition",
            "The agent unnecessarily redoes steps it already completed.",
            ["Track completed actions in an explicit working state and check it before each call.",
             "Short-circuit identical (tool, args) calls with the recorded result (Approximately replay cache).",
             "Add a stop condition to the planning loop."],
            share=17.14),
        _fm("FM-1.4", FC1, "Loss of Conversation History",
            "Context is unexpectedly truncated or an earlier state resurfaces.",
            ["Pin critical facts (task, constraints, completed steps) outside the evictable window.",
             "Compress instead of truncate: summarize evicted turns and inject the summary.",
             "Audit context-management code paths that rebuild prompts."],
            share=3.33),
        _fm("FM-1.5", FC1, "Unaware of Termination Conditions",
            "The agent does not recognize when the interaction should end.",
            ["Emit an explicit done/undone checklist before every stop decision.",
             "Encode termination as a verifiable predicate over state, not a vibe."],
            share=9.82),
        _fm("FM-2.1", FC2, "Conversation Reset",
            "A dialogue restarts without warrant, discarding progress.",
            ["Make restarts explicit events with a carried-over state summary.",
             "Detect and block re-entry of the seed prompt mid-run (Approximately ConversationResetDetector)."],
            share=2.33),
        _fm("FM-2.2", FC2, "Fail to Ask for Clarification",
            "The agent proceeds on wrong assumptions instead of asking.",
            ["Add an assumption ledger; force a clarification turn when >1 assumption is unverified.",
             "Gate high-cost actions on confirmation."],
            share=11.65),
        _fm("FM-2.3", FC2, "Task Derailment",
            "The trajectory drifts away from the intended objective.",
            ["Re-anchor every K steps: restate the objective and diff against recent actions.",
             "Score each step's relevance to the objective; halt when it decays."],
            share=7.15),
        _fm("FM-2.4", FC2, "Information Withholding",
            "An agent fails to share information other agents need.",
            ["Use a shared scratchpad with mandatory write-back after tool calls.",
             "Define inter-agent contracts (what must be published, when)."],
            share=1.66),
        _fm("FM-2.5", FC2, "Ignored Other Agent's Input",
            "Input or recommendations from other agents are disregarded.",
            ["Require explicit accept/reject decisions for peer input, logged in state."],
            share=0.17),
        _fm("FM-2.6", FC2, "Reasoning-Action Mismatch",
            "Stated reasoning does not match the action actually taken.",
            ["Emit actions as structured tool calls derived from the plan step, not free text.",
             "Validate that the chosen tool matches the announced subtask before execution."],
            share=13.98),
        _fm("FM-3.1", FC3, "Premature Termination",
            "The agent ends the task before objectives are met.",
            ["Require a completion checklist (goal predicates) to pass before terminating.",
             "Make the final response template include evidence for each goal."],
            share=7.82),
        _fm("FM-3.2", FC3, "No or Incomplete Verification",
            "Outputs are not checked, letting errors propagate.",
            ["Insert an explicit verification step after every mutating action (MAST intervention: +15.6%).",
             "Mark mutating tools in the tool registry; auto-append verify calls."],
            share=6.82),
        _fm("FM-3.3", FC3, "Incorrect Verification",
            "Verification is attempted but validates the wrong thing or is too weak.",
            ["Verify against the original task criteria, not the agent's own claims.",
             "Use independent evidence (fresh tool read) rather than recalled state."],
            share=6.66),
    ]
}

OTHER = "OTHER"
FAILURE_MODES[OTHER] = _fm(
    OTHER, FC1, "Unclassified",
    "No MAST mode matched with sufficient confidence.",
    ["Re-run with the LLM judge enabled (approximately attribute --judge).",
     "Inspect the HTML report timeline manually."],
)


def get_mode(mode_id: str) -> FailureMode:
    return FAILURE_MODES.get(mode_id, FAILURE_MODES[OTHER])


def all_modes() -> List[FailureMode]:
    ordered = sorted(
        (m for m in FAILURE_MODES.values() if m.id != OTHER),
        key=lambda m: (m.category, -(m.mast_share or 0)),
    )
    return ordered + [FAILURE_MODES[OTHER]]
