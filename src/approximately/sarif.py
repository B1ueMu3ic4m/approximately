"""SARIF 2.1.0 export: attribution results as GitHub code-scanning alerts.

Uploading the emitted file via `github/codeql-action/upload-sarif` makes
agent-failure detections appear in the repository's Security tab and as
PR annotations — agent failures reviewed with the same workflow as linters.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .attributor import FailureReport
from .taxonomy import FAILURE_MODES

SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
VERSION = "2.1.0"

_LEVELS = {"FC1": "warning", "FC2": "warning", "FC3": "error"}


def _build_rules(mode_ids: set) -> List[Dict[str, Any]]:
    rules = []
    for mode_id in sorted(mode_ids):
        mode = FAILURE_MODES.get(mode_id)
        if mode is None:
            continue
        rules.append({
            "id": mode.id,
            "name": mode.name.replace(" ", ""),
            "shortDescription": {"text": f"{mode.label}: {mode.definition}"},
            "helpUri": "https://arxiv.org/abs/2503.13657",
            "properties": {"category": mode.category_name,
                           "mastShare": mode.mast_share},
        })
    return rules


def _build_results(reports: List[FailureReport]) -> List[Dict[str, Any]]:
    results = []
    for rep in reports:
        if not rep.failed:
            continue
        for det in rep.detections:
            mode = FAILURE_MODES.get(det.mode_id)
            if mode is None:
                continue
            results.append({
                "ruleId": det.mode_id,
                "level": _LEVELS.get(mode.category, "warning"),
                "message": {
                    "text": f"{rep.task[:100]} - {rep.summary} "
                            f"(evidence: {'; '.join(det.evidence)})"
                },
                "locations": [{
                    "physicalLocation": {
                        "artifactLocation": {
                            "uri": f"traces/{rep.trace_id}.json",
                            "uriBaseId": "STORE",
                        },
                        "region": {"startLine": det.step_index + 1},
                    },
                    "logicalLocations": [{"name": f"step-{det.step_index}"}],
                }],
                "partialFingerprints": {
                    "traceId": rep.trace_id,
                    "stepIndex": str(det.step_index),
                },
                "properties": {"confidence": round(det.confidence, 3),
                               "source": det.source},
            })
    return results


def to_sarif(reports: List[FailureReport]) -> Dict[str, Any]:
    """Render one or more FailureReports as a SARIF 2.1.0 log."""
    used_modes = {r.primary_mode.id for r in reports if r.failed}
    for rep in reports:
        used_modes.update(d.mode_id for d in rep.detections)
    return {
        "$schema": SCHEMA,
        "version": VERSION,
        "runs": [{
            "tool": {
                "driver": {
                    "name": "approximately",
                    "informationUri":
                        "https://github.com/B1ueMu3ic4m/approximately",
                    "rules": _build_rules(used_modes),
                }
            },
            "results": _build_results(reports),
            "automationDetails": {
                "description": "approximately agent-failure attribution"
            },
        }],
    }
