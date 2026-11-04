"""v369: the audit job installs what it audits.

v3.67.1's sha-pin rewrite deleted agent-audit's ``pip install .``
and its demo-store step; the next scheduled run died with
``approximately: command not found`` — and the dispatch run that
"verified" the workflow had executed before the deletion merged,
so nothing saw it. The contract, held from now on: any workflow
that invokes the ``approximately`` CLI installs the package
first, and any workflow that audits a fresh store records
something for it to judge. Text-scanned — no yaml in the
zero-dep env.
"""

from pathlib import Path

_WF = (Path(__file__).resolve().parents[1]
       / ".github" / "workflows")


def _calls(lines):
    # the command-not-found failure mode: a run block invoking the
    # bare CLI. `fresh/bin/approximately` and `python -m` shapes
    # carry their own interpreter, so they are not this trap.
    return [i for i, line in enumerate(lines)
            if line.strip().startswith("approximately ")]


def _installs(lines):
    return [i for i, line in enumerate(lines)
            if line.strip().startswith(("- run: pip install",
                                        "run: pip install"))]


def _cli_workflows():
    out = []
    for wf in sorted(_WF.glob("*.yml")):
        lines = wf.read_text(encoding="utf-8").splitlines()
        if _calls(lines):
            out.append((wf, lines))
    return out


def test_every_cli_workflow_installs_the_package_first():
    offenders = []
    cli_workflows = _cli_workflows()
    assert len(cli_workflows) >= 2, \
        "agent-gate and agent-audit should both invoke the CLI"
    for wf, lines in cli_workflows:
        installs = _installs(lines)
        if not installs:
            offenders.append(f"{wf.name}: no `pip install .` step")
            continue
        for c in _calls(lines):
            if not any(i < c for i in installs):
                offenders.append(
                    f"{wf.name}:{c + 1}: the CLI runs before "
                    "the install")
                break
    assert not offenders, "offenders: " + "; ".join(offenders)


def test_the_audit_records_a_store_it_can_judge():
    lines = (_WF / "agent-audit.yml").read_text(
        encoding="utf-8").splitlines()
    assert any("examples/record-demo.py" in line
               for line in lines), \
        "a fresh runner has no traces; --min-traces 1 needs a store"


def test_the_recorded_fixture_still_exists():
    root = Path(__file__).resolve().parents[1]
    assert (root / "examples" / "record-demo.py").is_file(), \
        "both workflows invoke this; deleting it kills the channel"
