# Release runbook

Everything here is mechanical; the discipline is in the order. The
rule this repo works by: **main is always releasable** — a release is
a tag, not an event.

## 0. One-time setup (repo owner, already documented in release.yml)

PyPI Trusted Publishing: pypi.org → your project → Publishing →
GitHub publisher, workflow name `release.yml`, environment `pypi`.
No API token lives anywhere.

## 1. Pre-tag checklist (all gates locally, so CI is a formality)

```console
$ python3 -m pytest -q                  # full suite, 0 failures
$ ruff check src tests examples
$ mypy src/approximately --ignore-missing-imports
$ xenon --max-absolute C --max-modules B --max-average A src
$ python scripts/bench_gate.py && python scripts/bench_gate.py --synth
$ python scripts/perf_gate.py
$ python -m approximately.cli demo      # the 30-second tour still tours
```

## 2. Version bump

`pyproject.toml` and `src/approximately/__init__.py` carry the
version — both must match (CI's packaging job installs from the
wheel, so a mismatch ships silently wrong metadata). Update the
README roadmap line for the release, and make sure
[docs/PLAN.md](PLAN.md) items delivered in this release are marked ✅.

## 3. Tag and push

```console
$ git tag vX.Y.Z && git push origin vX.Y.Z
```

The tag must equal the `pyproject.toml` version with a `v` prefix —
there is no automation enforcing this today, so the checklist does.

## 4. What CI does from here

1. `build` job: sdist + wheel, uploaded as an artifact.
2. `publish` job: Trusted-Publishes both artifacts to PyPI
   (environment `pypi`, OIDC, no token).

Watch the Release run; if `publish` fails on a trust-setup error it
is always the one-time setup, never the code.

## 5. After the release

- `pip install approximately` in a clean venv and run `approximately
  demo` — the same promise as the README's first line.
- GitHub Release notes: paste the release's roadmap bullet from the
  README; it is already written for humans.
- The repo description is short; update it only when the tool gains
  a capability users search for, not per release.

## Rollback

PyPI does not delete releases. If a release is broken, yank it
(PyPI → releases → yank) and tag a patch release from the last good
commit; the tag history stays honest.
