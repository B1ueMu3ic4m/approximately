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

## 3. Budget policy

Treat `--min-recall` like coverage: start at your current measured recall
(`approximately context <trace> --budget B`) and ratchet it up. A PR that
shrinks the effective budget below the ratchet fails exactly like a
dropping test suite.
