# Contributing to approximately

Thanks for helping make agents accountable. This project keeps a
deliberately small surface: a zero-dependency core, three small interfaces
(Recorder / Attributor / Replayer), and lazy-import adapters.

## Development setup

```bash
git clone https://github.com/B1ueMu3ic4m/approximately
cd approximately
pip install -e ".[dev]"
pytest -q
```

Optional extras used by parts of the test suite (tests skip cleanly when
absent): `pip install openai langchain-core openai-agents`

## Ground rules

1. **Zero dependencies in the core.** `src/approximately/*.py` (except
   `contrib/`) must import only the standard library. If you need an
   external package, make it a lazy optional import with graceful
   degradation — see `judge.py` for the pattern.
2. **Evidence or it didn't happen.** Every detector `Detection` must carry
   human-readable evidence lines pointing at exact step indices.
3. **Attribution never hard-fails.** Any new optional path (network,
   tokenizer, framework) must degrade to rules-only behavior.
4. **Every detector ships with tests** covering: fires on a synthetic
   failing trace, silent on a healthy trace, and evidence content.
5. **Determinism**: the same trace must always produce the same report.

## Good first issues

- Rule detectors for the remaining multi-agent MAST modes (FM-2.2, FM-2.4,
  FM-2.5 are covered; FM-1.2 role-spec heuristics are open)
- More framework adapters (AutoGen, LlamaIndex, ...)
- Optional exact tokenizer integrations beyond tiktoken

## Complexity gate

CI runs `xenon --max-absolute C --max-modules B --max-average A src`:
no function may reach D-grade cyclomatic complexity (20+), module averages
stay B or better, overall average A. When you touch a C-grade function,
extract helpers instead of adding branches.

## Static analysis (all must pass)

```bash
ruff check src tests examples     # lint (config in pyproject.toml)
mypy src/approximately --ignore-missing-imports
bandit -r src -q                  # security; zero findings is the bar
```

Core dependency rule is enforced by review: `src/approximately/**` (except
`contrib/`) may import only the standard library; optional integrations are
lazy imports behind extras.

## Pull requests

- Branch from `main`, keep the change focused.
- `pytest -q` green locally; CI runs the same suite on 3 OSes × 3 Pythons
  plus judge-integration and framework-adapter jobs.
- Update `CHANGELOG.md` under the unreleased heading.
