"""The module outcomes as a data file (`modules.json`): which modules ran and why others did not."""

import json

from actuarycanary.modules.reserving import ReservingResult, methods_run
from actuarycanary.modules.runner import AnalysisResult


def analysis_json(analysis: AnalysisResult, reserving: ReservingResult | None = None) -> str:
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
    document: dict[str, object] = {"modules": modules}
    if reserving is not None:
        document["methods_run"] = methods_run(reserving)
        document["diagnostics"] = [
            {"segment": group[0], "line": group[1], "count": count}
            for group, count in reserving.diagnostics_by_group().items()
        ]
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"
