"""The context runtime: manage what the agent sees as a bounded resource.

This is the second half of Approximately: the flight recorder tells you what
the agent *did*, the context runtime tells you what the agent could *see* —
and what your context policy silently destroyed.

Core ideas (see docs/PLAN.md §2.6):

- **Budgeted window** — context is a budget, not a dumping ground. Items are
  evicted oldest-first, with pins and class priority as guardrails.
- **Pins** — task spec, constraints, and critical facts are never evicted.
  (The mechanical prevention for MAST FM-1.4, Loss of Conversation History.)
- **Recall probe** — after any policy decision, probe which critical facts
  are still renderable. Effective recall is a number, not a vibe.
- **Forecast** — replay a recorded trace through a budget to get the
  cost-vs-recall curve *before* you deploy that budget to production.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from .trace import TOOL_CALL, Trace

# Rough token estimate; deliberately tokenizer-free (stdlib only).
# Set APPROXIMATELY_EXACT_TOKENS=1 with tiktoken installed for exact
# cl100k_base counting (approx 10x slower; off by default).
_EXACT_TOKENS = None


def _use_exact() -> bool:
    global _EXACT_TOKENS
    if _EXACT_TOKENS is None:
        import os

        _EXACT_TOKENS = (
            os.environ.get("APPROXIMATELY_EXACT_TOKENS") == "1"
        )
    return _EXACT_TOKENS


def estimate_tokens(text: str) -> int:
    if _use_exact():
        try:  # pragma: no cover - exercised only with tiktoken installed
            import tiktoken

            enc = tiktoken.encoding_for_model("gpt-4o")
            return max(1, len(enc.encode(text)))
        except Exception:
            pass
    return max(1, len(text) // 4)


# Context item classes, in eviction priority order (first = evicted first).
TOOL_RESULT = "tool_result"
OBSERVATION = "observation"
PLAN = "plan"
SUMMARY = "summary"
FACT = "fact"
TASK = "task"

EVICT_ORDER = (TOOL_RESULT, OBSERVATION, PLAN, SUMMARY, FACT, TASK)


@dataclass
class ContextItem:
    key: str
    kind: str
    text: str
    tokens: int
    pinned: bool = False

    def render(self) -> str:
        return f"[{self.kind}] {self.key}: {self.text}"


@dataclass
class ProbeResult:
    """Effective recall over a set of critical facts."""

    kept: List[str] = field(default_factory=list)
    lost: List[str] = field(default_factory=list)

    @property
    def recall(self) -> float:
        total = len(self.kept) + len(self.lost)
        return len(self.kept) / total if total else 1.0

    def summary(self) -> str:
        return (f"effective recall {self.recall:.0%} "
                f"({len(self.kept)} kept, {len(self.lost)} lost)")


@dataclass
class EvictionEvent:
    at_step: int
    item_key: str
    item_kind: str
    tokens: int


Summarizer = Callable[[List[ContextItem]], str]


class ContextRuntime:
    """A budgeted, policy-managed context window."""

    def __init__(self, budget: int, task: str = ""):
        self.budget = budget
        self.items: List[ContextItem] = []
        self.evictions: List[EvictionEvent] = []
        self._step = 0
        if task:
            self.pin("task", task, kind=TASK)

    # -- writing -------------------------------------------------------------
    def pin(self, key: str, text: str, kind: str = FACT) -> ContextItem:
        item = ContextItem(key=key, kind=kind, text=text,
                           tokens=estimate_tokens(text), pinned=True)
        self._upsert(item)
        return item

    def add_tool_result(self, key: str, text: str) -> ContextItem:
        item = ContextItem(key=key, kind=TOOL_RESULT, text=text,
                           tokens=estimate_tokens(text))
        self._upsert(item)
        self._enforce_budget(at_step=self._step)
        return item

    def advance(self) -> None:
        """Mark a step boundary (evictions are attributed to steps)."""
        self._step += 1

    def compact(self, summarizer: Summarizer) -> ContextItem:
        """Fold every evictable item into one summary item.

        The summary takes the position of the first item it replaces, so
        pinned context keeps its relative order around it.
        """
        evictable = [i for i in self.items if not i.pinned]
        if not evictable:
            return ContextItem(key="nothing-to-compact", kind=SUMMARY,
                               text="", tokens=0)
        insert_at = min(self.items.index(i) for i in evictable)
        text = summarizer(evictable)
        for item in evictable:
            self.items.remove(item)
        summary = ContextItem(key=f"summary@{self._step}", kind=SUMMARY,
                              text=text, tokens=estimate_tokens(text))
        self.items.insert(insert_at, summary)
        return summary

    # -- reading ---------------------------------------------------------------
    def render(self) -> List[ContextItem]:
        """The context exactly as the model would see it, in order."""
        return list(self.items)

    def used_tokens(self) -> int:
        return sum(i.tokens for i in self.items)

    # -- probing -----------------------------------------------------------------
    def recall_probe(self, facts: Dict[str, str]) -> ProbeResult:
        """Check which critical facts are still present verbatim.

        ``facts`` maps a fact key to a substring that must appear in the
        rendered context for the fact to count as recalled.
        """
        rendered = "\n".join(i.render() for i in self.items)
        kept, lost = [], []
        for key, needle in facts.items():
            (kept if needle in rendered else lost).append(key)
        return ProbeResult(kept=kept, lost=lost)

    # -- internals -----------------------------------------------------------------
    def _upsert(self, item: ContextItem) -> None:
        for i, existing in enumerate(self.items):
            if existing.key == item.key:
                self.items[i] = item
                return
        self.items.append(item)

    def _over_budget(self) -> bool:
        return self.used_tokens() > self.budget

    def _enforce_budget(self, at_step: int) -> None:
        while self._over_budget():
            victim = self._pick_victim()
            if victim is None:
                break  # everything pinned: over budget is the honest state
            self.items.remove(victim)
            self.evictions.append(
                EvictionEvent(at_step=at_step, item_key=victim.key,
                              item_kind=victim.kind, tokens=victim.tokens)
            )

    def _pick_victim(self) -> Optional[ContextItem]:
        for kind in EVICT_ORDER:
            for item in self.items:
                if item.kind == kind and not item.pinned:
                    return item
        # all unpinned exhausted? evict oldest unpinned of any kind (none left)
        return None


@dataclass
class StepForecast:
    step_index: int
    tool: str
    tokens_used: int
    evicted_keys: List[str]
    lost_facts: List[str]


@dataclass
class ContextForecast:
    """What a budget *would* do to a recorded trace."""

    trace_id: str
    budget: int
    steps: List[StepForecast] = field(default_factory=list)
    facts: Dict[str, str] = field(default_factory=dict)
    final_probe: ProbeResult = field(default_factory=ProbeResult)
    full_context_tokens: int = 0
    evicted_count: int = 0

    @property
    def final_recall(self) -> float:
        return self.final_probe.recall

    @property
    def budgeted_tokens(self) -> int:
        return self.steps[-1].tokens_used if self.steps else 0

    def summary(self) -> str:
        saved = self.full_context_tokens - self.budgeted_tokens
        lines = [
            f"context forecast for {self.trace_id} @ budget {self.budget} tokens",
            f"  full context: {self.full_context_tokens} tokens | "
            f"budgeted: {self.budgeted_tokens} | saved: {max(saved, 0)}",
            f"  evictions: {self.evicted_count} | "
            + self.final_probe.summary(),
        ]
        if self.final_probe.lost:
            lines.append(f"  lost facts: {', '.join(self.final_probe.lost)}")
            lines.append("  hint: pin critical facts (runtime.pin) or raise the budget")
        else:
            lines.append("  all critical facts survive this budget")
        return "\n".join(lines)


def default_facts(trace: Trace) -> Dict[str, str]:
    """One probe fact per tool: the head of its first successful result."""
    facts: Dict[str, str] = {}
    for step in trace.steps:
        if step.kind == TOOL_CALL and not step.error and step.result:
            needle = " ".join(step.result.split())[:40]
            facts.setdefault(f"{step.tool}#{step.index}", needle)
    return facts


def forecast(trace: Trace, budget: int,
             facts: Optional[Dict[str, str]] = None) -> ContextForecast:
    """Replay a recorded trace through a budgeted runtime (dry run).

    Every tool result is added in order; the budget is enforced after each
    add. Facts can only be *lost* when an eviction happens, so the probe
    runs incrementally: aligned facts (keys that name the item they came
    from) are re-verified only on eviction batches, which keeps forecasting
    large traces linear-ish instead of O(steps x facts). The final probe is
    always computed exactly. Nothing mutates the trace.
    """
    facts = facts if facts is not None else default_facts(trace)
    runtime = ContextRuntime(budget=budget, task=trace.task)
    out = ContextForecast(trace_id=trace.id, budget=budget, facts=dict(facts))

    lost: set = set()
    pending: set = set()  # aligned facts whose item was evicted: re-verify

    def _render() -> str:
        return "\n".join(i.render() for i in runtime.items)

    for step in trace.steps:
        runtime.advance()
        evicted_now = []
        if step.kind == TOOL_CALL and step.result:
            key = f"{step.tool}#{step.index}"
            runtime.add_tool_result(key=key, text=step.result)
        for event in runtime.evictions:
            if event.at_step == runtime._step:
                evicted_now.append(event.item_key)
        lost_now: list = []
        if evicted_now:
            # facts whose supporting item just left must re-prove themselves
            for fact_key in facts:
                if fact_key in evicted_now:
                    pending.add(fact_key)
            if pending:
                rendered = _render()
                for fact_key in sorted(pending):
                    if facts[fact_key] not in rendered:
                        lost.add(fact_key)
                        lost_now.append(fact_key)
                pending -= lost
        out.steps.append(
            StepForecast(step_index=step.index, tool=step.tool or step.kind,
                         tokens_used=runtime.used_tokens(),
                         evicted_keys=evicted_now,
                         lost_facts=lost_now)
        )

    out.final_probe = runtime.recall_probe(facts)
    out.full_context_tokens = sum(
        estimate_tokens(s.result) + 8 for s in trace.steps if s.result
    ) + estimate_tokens(trace.task)
    out.evicted_count = len(runtime.evictions)
    if out.steps:
        out.steps[-1].tokens_used = runtime.used_tokens()
    return out


def render_forecast_text(forecast: ContextForecast) -> str:
    return forecast.summary()
