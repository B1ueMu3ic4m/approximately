# Running approximately guards in CI

## 1. Generate guards from your recorded failures (locally)

```bash
approximately test <trace-id> -o tests/test_agent_regressions.py
approximately test <trace-id> --budget 800 --min-recall 0.8 \
    -o tests/test_context_budget.py
```

Commit the generated files. They are self-contained (traces ride along as
base64) and run under plain pytest.

## 2. GitHub Actions

```yaml
name: agent-regressions
on: [pull_request]
jobs:
  guards:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.12"}
      - run: pip install approximately pytest
      - run: pytest tests/test_agent_regressions.py tests/test_context_budget.py -v
```

Optional: keep a weekly `approximately stats` comment on your README-ish
dashboard by running the CLI over your production trace store artifact.

## 4. Attribution-quality gate (if you keep a gold corpus)

If you maintain labeled traces, pin attribution quality the same way:
`scripts/bench_gate.py` compares rule-detector precision/recall/F1
against per-mode floors (`docs/bench-floors.json`) and exits 1 on
regression. Upstream runs it as the `bench-gate` CI job on every PR.

## 5. Fleet trend gate

If you run `approximately fleet --watch`, point a cron (or scheduled
workflow) at `approximately fleet --trend --digest-dir DIR
--fail-on-worsening`: it exits 1 when the day-level Theil-Sen verdict
turns worsening, and `doctor --digest-dir DIR` (add `--fix` to clean
stale writer locks and leftover temp files) reports monitoring gaps
for the same window.

## 3. Budget policy

Treat `--min-recall` like coverage: start at your current measured recall
(`approximately context <trace> --budget B`) and ratchet it up. A PR that
shrinks the effective budget below the ratchet fails exactly like a
dropping test suite.
