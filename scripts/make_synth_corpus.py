#!/usr/bin/env python3
"""Deterministic synthetic regression fixture for the attribution bench.

Generates labeled multi-label prose traces where each failure mode is
planted *by construction*: the generator knows exactly which modes a
scenario exhibits, so the gold labels need no human annotation. The
shape mirrors the real MAST-Data prose records (harness turns carry
"Thought: ... Action: ..." text; scenario thoughts carry the same
domain keywords as the task, as real inner-loop chatter does).

What this fixture is for - and what it is NOT for:

- IS: a large-n regression signal. Real gold data is scarce (n=27,
  Wilson intervals several tenths wide); this fixture has 180
  records, so a detector refactor that silently degrades precision or
  recall shows up with tight intervals in CI.
- IS NOT: evidence of real-world performance. The traces come from
  the same imagination as the detectors, so the numbers here flatter
  the detectors and must never be quoted next to the MAST gold
  corpus numbers. FM-2.3/FM-3.1 are intentionally absent: the
  derailment signal does not exist at record level (see the FM-2.3
  deferral in this plan) and prose FM-3.1 has no rule detector.

Usage: python3 scripts/make_synth_corpus.py > docs/mast-bench-synth.jsonl
Deterministic under SEED; regeneration is idempotent.
"""

from __future__ import annotations

import json
import random
import sys

SEED = 20260919

SCENARIOS_PER_KIND = 30


def _turn(i, tool, args, thought, observation):
    text = f"Thought: {thought} Action: {tool} {args}. {observation}"
    return {"kind": "tool_call", "tool": tool, "args": args,
            "result": text, "index": i, "tokens": 40}


def _finish(steps, response, success, labels, task):
    steps.append({"kind": "response", "result": response,
                  "index": len(steps), "tokens": 30})
    return {"task": task, "model": "synthetic/fixture",
            "success": success, "final_output": response,
            "meta": {"prose": True}, "steps": steps, "labels": labels}


def healthy_run(rng, i):
    task = (f"Stabilize the flaky retry suite for service {i} "
            f"before the Friday release cut.")
    steps = []
    thoughts = [
        (f"svc{i}_mod0.py",
         ("Start by reading the timeout constants at the top; if "
          "they are seeded deterministically the flake is ordering, "
          "not timing."), "constants look deterministic."),
        (f"svc{i}_mod1.py",
         ("Next suspect: the retry decorator on the request helper. "
          "Check where its jitter range comes from."),
         "jitter draws from a fixed range."),
        (f"svc{i}_mod2.py",
         ("Before touching code, profile two runs side by side and "
          "compare the call order of the fixture setup."),
         "no shared state; ordering is the suspect."),
        (f"svc{i}_mod3.py",
         ("The fixtures look unordered - pin the seed per test case "
          "and rerun to see whether the flake disappears."),
         "seed pinned per case."),
    ]
    for j, (path, thought, finding) in enumerate(thoughts):
        steps.append(_turn(
            len(steps), f"inspect_module_{j}", {"module": path},
            thought, finding))
    steps.append(_turn(
        len(steps), "run_tests", {"suite": f"svc{i}"},
        "running the full retry tests to confirm the flake is gone.",
        "12 passed, 0 failed in 0.4s."))
    return _finish(steps, "all 12 tests passed, suite is stable",
                   True, [], task)


def repetition_cycle(rng, i):
    task = (f"Repair the payment retry backoff in checkout service "
            f"{i} reported by the nightly run.")
    tools = ["plan_iteration", "apply_patch", "inspect_result"]
    steps = []
    for turn in range(8):  # 24 calls in one 3-call cycle
        variants = [
            ((f"iteration {turn}: the backoff ceiling needs raising "
              f"again; plan that change."),
             f"planned iteration {turn}."),
            ((f"apply the ceiling change from iteration {turn} to "
              f"the checkout patch."),
             f"patch applied for iteration {turn}."),
            ((f"did iteration {turn} move the failure? inspect the "
              f"result and decide."),
             f"latency unchanged after iteration {turn}."),
        ]
        for t, (thought, obs) in zip(tools, variants):
            steps.append(_turn(len(steps), t, {"turn": turn},
                               thought, obs))
    steps.append(_turn(
        len(steps), "run_tests", {"suite": f"checkout{i}"},
        "running the checkout suite after the backoff changes.",
        "3 failed, 9 passed: retry cases still time out."))
    # a pure loop is also a restart: every iteration re-runs the same
    # three-step approach with near-identical reasoning (the real gold
    # corpus double-labels exactly this shape, e.g. f8a804ecdb84)
    return _finish(steps, "still failing after 8 iterations, "
                           "stopping here", False,
                   ["FM-1.3", "FM-2.1"], task)


def no_verification(rng, i):
    task = (f"Fix the double-charge bug in invoice worker {i} "
            f"flagged by finance.")
    edits = [
        "adding the idempotency key to the charge intent",
        "moving the ledger write behind the state check",
        "hashing the request fingerprint into the guard",
        "gating the refund path on the dedup table",
    ]
    steps = []
    for j, note in enumerate(edits):
        steps.append(_turn(
            len(steps), f"edit_worker_{j}",
            {"file": f"invoice_worker_{i}_{j}.py"},
            f"{note} in invoice_worker_{i}_{j}.py.",
            f"applied: {note}."))
    return _finish(steps, "the double-charge issue is resolved",
                   False, ["FM-3.2"], task)


def trajectory_restart(rng, i):
    task = (f"Migrate the billing cron for tenant {i} onto the new "
            f"scheduler without dropping jobs.")
    opening = (f"Plan for tenant {i}: inventory the billing cron "
               "jobs, patch the `scheduler.register` call sites, run "
               "the migration dry-run, then report leftover jobs.")
    steps = [_turn(0, "plan_inventory", {"tenant": i}, opening,
                   "inventory noted.")]
    reads = [
        ("nightly-rollup", "3 AM daily, queue billing-rollup"),
        ("invoice-export", "hourly at :15, queue billing-export"),
        ("dunning-cycle", "every 6 hours, queue billing-dunning"),
        ("usage-meter", "5-minute cadence, queue billing-meters"),
    ]
    for j, (name, sched) in enumerate(reads, start=1):
        steps.append(_turn(
            len(steps), f"read_cron_{j}", {"job": f"{name}.yaml"},
            f"reading {name}.yaml: which queue owns it and when does "
            f"it fire.",
            f"job {name}: {sched}."))
    steps.append(_turn(5, "plan_restart", {"tenant": i}, opening,
                       "re-running the plan from the top."))
    patches = [
        "swap the cron parser for scheduler.register",
        "wrap the export handler in the new adapter",
        "point dunning at the tenant-aware queue",
        "route meters through the batched writer",
    ]
    for j, note in enumerate(patches, start=1):
        steps.append(_turn(
            len(steps), f"patch_cron_{j}", {"job": f"job_{j}.yaml"},
            f"{note} - patching job_{j}.yaml again after the restart.",
            f"job {j} re-patched."))
    return _finish(steps, "restart finished; migration not verified",
                   False, ["FM-2.1"], task)


def premature_stop(rng, i):
    task = (f"Ship the ledger rollup patch for shard {i} in "
            f"today's window.")
    steps = [
        _turn(0, "build_rollup", {"shard": i},
              "building the ledger rollup binary for the shard.",
              "compiling..."),
        _turn(1, "build_rollup", {"shard": i},
              "rebuilding after the first pass.",
              "link error: undefined symbol rollup_shard(). "
              "Traceback in build log."),
    ]
    return _finish(steps, "the rollup build issue is resolved - "
                           "shipping the shard now",
                   False, ["FM-3.2"], task)


def thought_action_mismatch(rng, i):
    task = (f"Add the exponential backoff constant to the payment "
            f"retry path for merchant {i}.")
    steps = []
    for j in range(3):
        steps.append(_turn(
            len(steps), "edit_file",
            {"path": f"unrelated_notes_{j}.txt"},
            f"Next I will update `retry.backoff` and "
            f"`config.timeout` in payments/retry_{i}.py to add the "
            f"constant the traceback asked for.",
            f"wrote unrelated_notes_{j}.txt with a comment."))
    steps.append(_turn(
        len(steps), "run_tests", {"suite": f"payments{i}"},
        "running the payment retry tests to re-check the constant.",
        "2 failed, 10 passed: backoff constant still missing."))
    return _finish(steps, "tests still fail, pausing here",
                   False, ["FM-2.6"], task)


KINDS = [
    ("healthy", healthy_run),
    ("repetition_cycle", repetition_cycle),
    ("no_verification", no_verification),
    ("trajectory_restart", trajectory_restart),
    ("premature_stop", premature_stop),
    ("thought_action_mismatch", thought_action_mismatch),
]


def main() -> int:
    rng = random.Random(SEED)
    out = sys.stdout
    i = 0
    for kind, fn in KINDS:
        for _ in range(SCENARIOS_PER_KIND):
            rec = fn(rng, i)
            rec["id"] = f"synth-{i:04d}-{kind}"
            out.write(json.dumps(rec, sort_keys=True) + "\n")
            i += 1
    print(f"wrote {i} synthetic records (seed {SEED})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
