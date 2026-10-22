"""The module outcomes as a data file (`modules.json`): which modules ran and why others did not."""

import json

from actuarycanary.modules.runner import AnalysisResult


def analysis_json(analysis: AnalysisResult) -> str:
    modules = [
        {
            "module": m.module,
            "title": m.title,
            "state": m.state.value,
            "reasons": list(m.reasons),
            "methods_built": list(m.methods_built),
            "methods_missing": list(m.methods_missing),
            "measures": [
                {
                    "measure": r.measure,
                    "spec_version": r.version,
                    "breakdowns": list(r.request.breakdowns),
                    "basis": r.request.basis.label(),
                    "available": r.available,
                    "rows": r.rows,
                    "reason": r.reason,
                    "notes": list(r.notes),
                }
                for r in m.measures
            ],
        }
        for m in analysis.modules
    ]
    return json.dumps({"modules": modules}, indent=2, ensure_ascii=False) + "\n"
