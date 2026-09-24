# Release runbook

**Releases are fully automatic.** When a merge to main changes
`pyproject.toml`'s version, `autotag.yml` tags it and dispatches
`release.yml`, which creates the GitHub Release (auto-generated notes
from merged PRs, sdist + wheel attached) and attempts the PyPI
publish. The rule this repo works by holds: **main is always
releasable** — a release is a tag, and tags happen by themselves.

## 0. PyPI (the only piece that needs credentials, once)

Without credentials, everything above works and only the `pypi-publish`
job shows a notice (it is `continue-on-error` by design). To light up
PyPI, either works:

- **Trusted Publishing** (no token anywhere): pypi.org → your project
  → Publishing → GitHub publisher, workflow `release.yml`,
  environment `pypi`; or
- hand the owner's PyPI API token to the repo as the
  `PYPI_API_TOKEN` secret — the publish job picks it up
  automatically.

The PyPI name `approximately` is free (checked 2026-09-23); the
first successful publish claims it.

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

## 3. Tag and push (only if autotag did not already do it)

Manual tagging still works — `release.yml` triggers on any `v*` tag
push. The tag must equal the `pyproject.toml` version with a `v`
prefix; autotag enforces that by construction for its own tags.

## 4. What CI does from here

1. `build` job: sdist + wheel, uploaded as an artifact.
2. `publish` job: Trusted-Publishes both artifacts to PyPI
   (environment `pypi`, OIDC, no token), then creates the GitHub
   Release for the tag — notes auto-assembled from the merged PRs,
   sdist + wheel attached as assets. The Releases page is generated
   from tags: if it looks empty, no tag has been pushed yet.

> Historical note: until v0.50.0 the versions bumped only in code —
> `git tag` was never pushed, so the Releases page stayed empty even
> though main carried 53 delivered roadmap items.

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
