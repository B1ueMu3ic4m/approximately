"""Live budget rails for the flight recorder.

The ``ci`` quality gate settles accounts after the run is over; a
:class:`Budget` is the circuit breaker DURING it.  Every recorded tool
step is charged against token and dollar ceilings, and crossing one can
warn, raise, or simply be stamped into the trace for the post-hoc gates
to find.

Pricing follows the house convention used by every other pricing
surface (``stats --price-per-1k``, the ci gate): ``prices`` maps a model
name to USD per 1,000 tokens, spend is rounded to 4 decimal places, and
tokens from unpriced models are counted separately rather than silently
valued at zero — a live dollar ceiling is only as honest as its price
map, so ``unpriced_tokens`` travels with the state.
"""

from __future__ import annotations

import math
import sys
from typing import Any, Dict, Optional


class BudgetExceededError(RuntimeError):
    """Raised by ``on_exceed="raise"`` when a budget ceiling is crossed.

    The offending step is already on the record when this fires — the
    charge happens after :meth:`Recorder.tool` appends the step — so the
    saved trace shows exactly where the burn stopped.
    """

    def __init__(self, kind: str, limit: float, spent: float):
        self.kind = kind
        self.limit = limit
        self.spent = spent
        if kind.startswith("agent:"):
            head = f"agent {kind[6:]!r}"
            unit = "tokens"
        else:
            head = "run"
            unit = "tokens" if kind == "tokens" else "USD"
        super().__init__(
            f"budget exceeded: {head} {spent:,.4g}/{limit:,.4g} "
            f"{unit} ({kind} ceiling)")


class Budget:
    """Token and dollar ceilings enforced while a run is recorded.

    ``on_exceed`` selects the enforcement mode: ``"stamp"`` (default)
    only records the breach in :attr:`state` for the exit stamp,
    ``"warn"`` also prints one warning to stderr per newly crossed
    ceiling, and ``"raise"`` raises :class:`BudgetExceededError` from
    the charging call.
    """

    MODES = ("stamp", "warn", "raise")

    @staticmethod
    def _validate_prices(prices: Optional[Dict[str, float]]) -> None:
        """A negative price pays you to burn; inf/NaN never trip a
        ceiling (NaN compares false, inf belongs to no budget) — a
        price map that lies makes the dollar meter decorative."""
        if not prices:
            return
        bad = {m: v for m, v in prices.items()
               if isinstance(v, bool)
               or not isinstance(v, (int, float))
               or not math.isfinite(v) or v < 0}
        if bad:
            raise ValueError("prices must be finite non-negative "
                             f"numbers, got {bad}")

    @staticmethod
    def _validate_per_agent(per_agent: Optional[Dict[str, int]]) -> None:
        if not per_agent:
            return
        bad = {a: n for a, n in per_agent.items()
               if isinstance(n, bool) or not isinstance(n, int) or n < 1}
        if bad:
            raise ValueError("per-agent ceilings must be positive "
                             f"ints, got {bad}")

    @staticmethod
    def validate_tokens(tokens: int) -> None:
        """Reject meter lies up front: token counts are non-negative
        ints.  Validation happens BEFORE the step is recorded — an
        impossible input never lands in a trace; a real input that
        breaches a ceiling lands first and THEN trips the breaker."""
        if isinstance(tokens, bool) or not isinstance(tokens, int) \
                or tokens < 0:
            raise ValueError(f"tokens must be a non-negative int, "
                             f"got {tokens!r}")

    def __init__(self,
                 tokens: Optional[int] = None,
                 usd: Optional[float] = None,
                 prices: Optional[Dict[str, float]] = None,
                 on_exceed: str = "stamp",
                 per_agent: Optional[Dict[str, int]] = None):
        if tokens is None and usd is None and not per_agent:
            raise ValueError("budget needs at least one ceiling: "
                             "tokens, usd, or per_agent")
        if on_exceed not in self.MODES:
            raise ValueError(f"on_exceed must be one of {self.MODES}, "
                             f"got {on_exceed!r}")
        if prices is None and usd is not None:
            raise ValueError("a usd ceiling needs a price map "
                             "(prices={model: usd per 1k tokens})")
        self._validate_prices(prices)
        self._validate_per_agent(per_agent)
        self.limit_tokens = tokens
        self.limit_usd = usd
        self.prices = dict(prices) if prices else {}
        self.on_exceed = on_exceed
        self.per_agent = dict(per_agent) if per_agent else {}
        self.agent_tokens: Dict[str, int] = {}
        self.tokens = 0
        self.unpriced_tokens = 0
        self.usd = 0.0
        self._warned: set = set()

    def charge(self, tokens: int = 0, model: Optional[str] = None,
               agent: Optional[str] = None) -> Dict[str, Any]:
        """Charge ``tokens`` against the ceilings and return the state.

        Priced models move the dollar meter; unpriced ones only move
        ``unpriced_tokens`` (never silently valued at zero).  With
        ``per_agent`` configured and ``agent`` named, the agent's own
        ceiling meters too.  Raises in ``"raise"`` mode when a ceiling
        is crossed; warns in ``"warn"`` mode, once per newly crossed
        ceiling.
        """
        self.validate_tokens(tokens)
        self.tokens += tokens
        if model is not None and model in self.prices:
            self.usd = round(
                self.usd + tokens / 1000 * self.prices[model], 4)
        else:
            self.unpriced_tokens += tokens
        if agent is not None and agent in self.per_agent:
            self.agent_tokens[agent] = (self.agent_tokens.get(agent, 0)
                                        + tokens)
        reasons = self.exceeded_reasons()
        if reasons and self.on_exceed == "raise":
            self._raise_first(reasons)
        if reasons and self.on_exceed == "warn":
            for kind in reasons:
                if kind not in self._warned:
                    self._warned.add(kind)
                    print(f"budget warning: "
                          f"{self._describe(kind)} exceeded",
                          file=sys.stderr)
        return self.state

    def exceeded_reasons(self) -> list:
        """Which ceilings are crossed: global ones first (``tokens``,
        ``usd``), then per-agent ones (``agent:<name>``)."""
        reasons = []
        if self.limit_tokens is not None and self.tokens > self.limit_tokens:
            reasons.append("tokens")
        if self.limit_usd is not None and self.usd > self.limit_usd:
            reasons.append("usd")
        for name, limit in self.per_agent.items():
            if self.agent_tokens.get(name, 0) > limit:
                reasons.append(f"agent:{name}")
        return reasons

    @property
    def state(self) -> Dict[str, Any]:
        """Snapshot for the trace stamp: meters, ceilings, breach verdict."""
        out: Dict[str, Any] = {
            "tokens": self.tokens,
            "usd": self.usd,
            "unpriced_tokens": self.unpriced_tokens,
            "exceeded": bool(self.exceeded_reasons()),
        }
        if self.limit_tokens is not None:
            out["limit_tokens"] = self.limit_tokens
        if self.limit_usd is not None:
            out["limit_usd"] = self.limit_usd
        if self.per_agent:
            out["agents"] = {
                name: {"tokens": self.agent_tokens.get(name, 0),
                       "limit": limit,
                       "exceeded":
                           self.agent_tokens.get(name, 0) > limit}
                for name, limit in self.per_agent.items()}
        return out

    def _describe(self, kind: str) -> str:
        spent, limit = self._spent_of(kind), self._limit_of(kind)
        if kind.startswith("agent:"):
            return (f"agent {kind[6:]!r} {spent:,.4g}/{limit:,.4g} "
                    "tokens")
        unit = "tokens" if kind == "tokens" else "USD"
        return f"{spent:,.4g}/{limit:,.4g} {unit}"

    def _limit_of(self, kind: str) -> float:
        if kind.startswith("agent:"):
            return float(self.per_agent[kind[6:]])
        return (float(self.limit_tokens or 0) if kind == "tokens"
                else float(self.limit_usd or 0))

    def _spent_of(self, kind: str) -> float:
        if kind.startswith("agent:"):
            return float(self.agent_tokens.get(kind[6:], 0))
        return float(self.tokens) if kind == "tokens" else self.usd

    def _raise_first(self, reasons: list) -> None:
        # deterministic order: global ceilings first, then agents
        for preferred in ("tokens", "usd"):
            if preferred in reasons:
                kind = preferred
                break
        else:
            kind = reasons[0]
        raise BudgetExceededError(kind, self._limit_of(kind),
                                  self._spent_of(kind))


def simulate(trace: Any, tokens: Optional[int] = None,
             usd: Optional[float] = None,
             prices: Optional[Dict[str, float]] = None
             ) -> Dict[str, Any]:
    """Replay a recorded run against rails it did not have.

    Sizing question: "had this ceiling been armed, where would the
    run have stopped?"  Walks the recorded tool steps, charging each
    into a fresh Budget, and reports the first step that trips it —
    or that no ceiling in this configuration would have.  Savings
    are measured from the trip point to the run's recorded end
    (tokens the run burned after the step where it should have
    died); for runs that never trip, both savings are 0.
    """
    rails = Budget(tokens=tokens, usd=usd, prices=prices,
                   on_exceed="raise")
    steps = [s for s in trace.steps if s.kind == "tool_call"]
    total = sum(s.tokens or 0 for s in steps)
    saved_tokens = 0
    tripped_at = None
    for step in steps:
        try:
            rails.charge(tokens=step.tokens or 0, model=trace.model)
        except BudgetExceededError:
            tripped_at = step.index
            saved_tokens = total - sum(
                s.tokens or 0 for s in steps
                if s.index <= step.index)
            break
    saved_usd = 0.0
    if tripped_at is not None and prices and trace.model in prices:
        after = [s for s in steps if s.index > tripped_at]
        saved_usd = round(sum(s.tokens or 0 for s in after)
                          / 1000 * prices[trace.model], 4)
    return {
        "trace_id": trace.id,
        "would_trip": tripped_at is not None,
        "trip_step": tripped_at,
        "limit_tokens": tokens,
        "limit_usd": usd,
        "recorded_tokens": total,
        "saved_tokens": saved_tokens,
        "saved_usd": saved_usd,
    }
