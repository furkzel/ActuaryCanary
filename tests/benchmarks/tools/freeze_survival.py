# ruff: noqa: E501
# pyright: reportPrivateImportUsage=false, reportIndexIssue=false, reportArgumentType=false, reportCallIssue=false
"""Freeze the Cox references of MT19 with R survival (an external tool, record 0600).

Run once by hand:  uv run python tests/benchmarks/tools/freeze_survival.py
Needs Rscript with the survival package on the PATH. The tests never run R.
"""

import csv
import shutil
import subprocess
import tempfile
from pathlib import Path

from freeze_common import TIER_B_DIR, write_manifest

HERE = Path(__file__).resolve().parent
SCRIPT = "tests/benchmarks/tools/freeze_survival.R"

DATASETS = {
    "ovarian": {
        "title": "Cox proportional hazards on the ovarian cancer data (26 rows, no tied event times)",
        "data": "survival::ovarian (Edmunson et al.); time = futime, event = fustat",
        "model": "Surv(time, event) ~ age + resid.ds + rx + ecog.ps",
        "note": "No two event times coincide, so the Efron and Breslow rows are equal; use lung for ties.",
    },
    "lung": {
        "title": "Cox proportional hazards on the lung data (227 complete rows, many tied event times)",
        "data": "survival::lung, rows with missing age, sex or ph.ecog dropped; event = (status == 2)",
        "model": "Surv(time, event) ~ age + sex + ph.ecog",
        "note": "Tied event times separate Efron from Breslow.",
    },
}


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["Rscript", str(HERE / "freeze_survival.R"), tmp], check=True)
        for name, info in DATASETS.items():
            folder = TIER_B_DIR / f"MT19-cox-{name}"
            folder.mkdir(parents=True, exist_ok=True)
            shutil.copy(Path(tmp) / name / "data.csv", folder / "data.csv")
            # keep the values file in our line-ending and column layout
            with (Path(tmp) / name / "values.csv").open(newline="", encoding="utf-8") as handle:
                rows = list(csv.reader(handle))
            with (folder / "values.csv").open("w", newline="", encoding="utf-8") as handle:
                csv.writer(handle, lineterminator="\n").writerows(rows)
            survival_version, r_version = (
                (Path(tmp) / name / "versions.txt").read_text().splitlines()
            )
            write_manifest(
                folder,
                {
                    "id": f"MT19-cox-{name}",
                    "spec_ids": ["MT19"],
                    "kind": "external_reference",
                    "title": info["title"],
                    "source": {
                        "tool": "R survival",
                        "version": survival_version,
                        "r_version": r_version,
                        "data": info["data"],
                        "calls": [
                            f"coxph({info['model']}, ties = 'efron')",
                            f"coxph({info['model']}, ties = 'breslow')",
                        ],
                    },
                    "how_produced": f"Run {SCRIPT} through freeze_survival.py; values.csv holds the R output unchanged.",
                    "files": {"data": "data.csv", "values": "values.csv"},
                    "tolerance_note": "1e-5 relative (spec MT19 benchmark).",
                    "notes": [
                        info["note"],
                        "R is not a dependency of the platform and no test runs it (record 0600).",
                    ],
                },
            )
    print("done")


if __name__ == "__main__":
    main()
