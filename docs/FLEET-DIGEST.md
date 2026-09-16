# Scheduled fleet digest — the cron pattern

One agent team per store is the normal deployment; a *fleet* view only
helps if it arrives on a schedule, before anyone thinks to ask. This
is the whole pattern: `fleet` on a cron, POST the signed summary to
your chat endpoint, and fail the job when a trend is worsening so the
scheduler's own alerting picks it up.

## GitHub Actions

```yaml
# .github/workflows/fleet-digest.yml
name: fleet-digest
on:
  schedule:
    - cron: "0 8 * * 1-5"   # 08:00 UTC on weekdays
  workflow_dispatch: {}
jobs:
  digest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install approximately
      - name: survey stores and alert
        env:
          APPROXIMATELY_SIGNING_KEY: ${{ secrets.FLEET_SIGNING_KEY }}
        run: |
          approximately fleet \
            stores/team-a stores/team-b stores/ci-runner \
            --webhook "$FLEET_WEBHOOK_URL" \
            --fail-on-worsening
```

## Receiver-side verification

The JSON body is HMAC-SHA256-signed with `APPROXIMATELY_SIGNING_KEY`
when that variable is set. A receiver rejects unsigned or mis-signed
alerts:

```python
import hmac, hashlib

def verify_alert(body: bytes, signature: str, key: bytes) -> bool:
    expected = "sha256=" + hmac.new(key, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)
```

## Exit semantics

- `0` — no store's failure-rate trend is worsening
- `1` — at least one store is worsening (`--fail-on-worsening`); the
  failing store names are also in the webhook payload's
  `worsening_stores` list
- webhook transport failures print to stderr but do not change the
  exit path (the survey itself succeeded)

## Window the digest

Pair with `--since`-style triage: `stats --since 30` and
`cluster --since 14 --json` give the same window in machine-readable
form, so a digest can carry "what changed this month" rather than
"everything ever".
