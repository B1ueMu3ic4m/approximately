"""The flight recorder: zero-intrusion capture of agent runs.

Two usage styles:

1. Context manager for ad-hoc runs::

       with Recorder("book a flight") as rec:
           rec.plan("search flights, pick cheapest, book")
           res = search_flights("SFO", "NRT")
           rec.tool("search_flights", {"from": "SFO"}, result=res)
           ...

2. The :func:`agentstep` decorator, which records tool calls automatically
   (including errors) into the recorder installed on the current thread.
"""

from __future__ import annotations

import functools
import threading
import time
from typing import Any, Callable, Dict, Optional, TypeVar

from .store import TraceStore
from .trace import ERROR, OBSERVATION, PLAN, RESPONSE, TOOL_CALL, Step, Trace

_local = threading.local()

F = TypeVar("F", bound=Callable[..., Any])


def current_recorder() -> Optional["Recorder"]:
    return getattr(_local, "recorder", None)


class Recorder:
    """Records one agent run into a :class:`~approximately.trace.Trace`."""

    def __init__(
        self,
        task: str,
        model: str = "unknown",
        store: Optional[TraceStore] = None,
        save: bool = True,
    ):
        self.trace = Trace(task=task, model=model)
        self.store = store
        self.save_on_exit = save
        self.saved_path = None
        self._previous = None
        self._t0 = time.perf_counter()

    # -- context management -------------------------------------------------
    def __enter__(self) -> "Recorder":
        self._previous = getattr(_local, "recorder", None)
        _local.recorder = self
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        _local.recorder = self._previous
        if exc_type is not None:
            self.trace.add(
                Step(
                    kind=ERROR,
                    error=f"{exc_type.__name__}: {exc}",
                    latency_ms=self._elapsed_ms(),
                )
            )
            self.trace.success = False
        if self.save_on_exit and self.store is not None:
            self.saved_path = self.store.save(self.trace)
        return False  # never swallow exceptions

    # -- recording API -------------------------------------------------------
    def plan(self, thought: str, **meta: Any) -> Step:
        return self.trace.add(Step(kind=PLAN, thought=thought, meta=meta))

    def tool(self, name: str, args: Optional[Dict[str, Any]] = None,
             result: str = "", thought: Optional[str] = None,
             error: Optional[str] = None, **meta: Any) -> Step:
        return self.trace.add(
            Step(
                kind=TOOL_CALL,
                tool=name,
                args=args or {},
                result=str(result),
                thought=thought,
                error=error,
                latency_ms=self._elapsed_ms(),
                meta=meta,
            )
        )

    def observe(self, text: str, **meta: Any) -> Step:
        return self.trace.add(Step(kind=OBSERVATION, result=text,
                                   latency_ms=self._elapsed_ms(), meta=meta))

    def respond(self, text: str, success: bool = True, **meta: Any) -> Step:
        step = self.trace.add(
            Step(kind=RESPONSE, result=text, latency_ms=self._elapsed_ms(), meta=meta)
        )
        self.trace.success = success
        self.trace.final_output = text
        return step

    def fail(self, reason: str, **meta: Any) -> Step:
        self.trace.success = False
        return self.trace.add(Step(kind=ERROR, error=reason, meta=meta))

    def _elapsed_ms(self) -> int:
        return int((time.perf_counter() - self._t0) * 1000)


def agentstep(fn: F) -> F:
    """Decorator: record calls to ``fn`` as tool steps on the current recorder.

    Args passed to the tool should be JSON-serializable to appear in the
    fingerprint used for repeat detection; unserializable args are stringified.
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        rec = current_recorder()
        if rec is None:
            return fn(*args, **kwargs)
        call_args: Dict[str, Any] = {}
        try:
            call_args.update(dict(zip(fn.__code__.co_varnames, args)))
        except Exception:
            call_args["*args"] = [str(a) for a in args]
        call_args.update(kwargs)
        t0 = time.perf_counter()
        try:
            value = fn(*args, **kwargs)
        except Exception as exc:
            rec.trace.add(
                Step(
                    kind=TOOL_CALL,
                    tool=fn.__name__,
                    args=call_args,
                    error=f"{type(exc).__name__}: {exc}",
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                )
            )
            raise
        rec.trace.add(
            Step(
                kind=TOOL_CALL,
                tool=fn.__name__,
                args=call_args,
                result=str(value),
                latency_ms=int((time.perf_counter() - t0) * 1000),
            )
        )
        return value

    return wrapper  # type: ignore[return-value]
