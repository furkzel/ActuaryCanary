"""What a run folder says, read from the files the pipeline wrote (record 0704).

The result screen, the past runs and the findings shown while a run is going all read the output
folder, never the memory of a run, so a run started in a tab that was closed, or by the command
line, is shown the same way. Nothing here writes.
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl

from actuarycanary.manifest.run import MANIFEST_NAME
from actuarycanary.quality.output import QUALITY_NAME
from actuarycanary.report.render import REPORT_NAME

RUN_ID = re.compile(r"^[0-9a-f]{16}$")
ULTIMATES_NAME = "ultimates.csv"
PAST_RUNS_LIMIT = 200
FINDINGS_LIMIT = 300
SEVERITIES = ("BLOCKING", "WARNING", "INFO")


class RunNotFoundError(LookupError):
    """There is no finished run with this id under the output folder."""


def run_folder(out: Path, run_id: str) -> Path:
    """The folder of a finished run under `out`; the id must be a run id (no path)."""
    if not RUN_ID.fullmatch(run_id):
        raise RunNotFoundError(run_id)
    folder = out / run_id
    if not (folder / MANIFEST_NAME).is_file():
        raise RunNotFoundError(run_id)
    return folder


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _stamp(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="minutes")


def past_runs(out: Path) -> list[dict[str, Any]]:
    """The finished runs under `out`, newest first: id, date, language, basis, currency."""
    if not out.is_dir():
        return []
    found = [
        d
        for d in out.iterdir()
        if d.is_dir() and RUN_ID.fullmatch(d.name) and (d / MANIFEST_NAME).is_file()
    ]
    found.sort(key=lambda d: (d / MANIFEST_NAME).stat().st_mtime, reverse=True)
    rows: list[dict[str, Any]] = []
    for folder in found[:PAST_RUNS_LIMIT]:
        manifest = folder / MANIFEST_NAME
        row: dict[str, Any] = {
            "run_id": folder.name,
            "date": _stamp(manifest),
            "has_report": (folder / REPORT_NAME).is_file(),
        }
        try:
            settings = _json(manifest)["settings"]
            row |= {
                "language": settings.get("language"),
                "reinsurance": settings.get("bases", {}).get("reinsurance"),
                "value": settings.get("bases", {}).get("value"),
                "currency": settings.get("reporting_currency"),
                "version": _json(manifest).get("software", {}).get("actuarycanary"),
            }
        except (OSError, ValueError, KeyError):
            row["unreadable"] = True
        rows.append(row)
    return rows


def findings_summary(folder: Path) -> dict[str, Any] | None:
    """The data findings of `quality.json` in `folder`: score, counts by severity, the rules."""
    path = folder / QUALITY_NAME
    try:
        quality = _json(path)
    except (OSError, ValueError):
        return None
    findings = quality.get("findings", [])
    counts = {s: sum(1 for f in findings if f.get("severity") == s) for s in SEVERITIES}
    return {
        "score": quality.get("scores", {}).get("overall", {}).get("value"),
        "rules": quality.get("scores", {}).get("overall", {}).get("rules"),
        "counts": counts,
        "findings": [
            {
                "severity": f.get("severity"),
                "rule": f.get("rule"),
                "concept": f.get("concept"),
                "count": f.get("count"),
                "checked": f.get("checked"),
                "message": f.get("message"),
                "examples": [
                    f"{r.get('file')} [{r.get('sheet')}] row {r.get('row')}"
                    for r in f.get("refs", [])[:2]
                ],
            }
            for f in findings[:FINDINGS_LIMIT]
        ],
        "more": max(0, len(findings) - FINDINGS_LIMIT),
    }


def started_folder(out: Path, since: float) -> Path | None:
    """The run folder of this run, found by its files: the newest folder under `out` with a
    `quality.json` written at or after `since` (the pipeline names the folder by the run id only
    once the id is known)."""
    if not out.is_dir():
        return None
    best: tuple[float, Path] | None = None
    for folder in out.iterdir():
        if folder.name.startswith(".") or not folder.is_dir():
            continue
        try:
            stamp = (folder / QUALITY_NAME).stat().st_mtime
        except OSError:
            continue
        if stamp >= since and (best is None or stamp > best[0]):
            best = (stamp, folder)
    return None if best is None else best[1]


def headline(folder: Path) -> list[dict[str, Any]]:
    """Paid, incurred, ultimate (incurred chain ladder) and IBNR per segment and line, as the
    terminal summary shows them; empty when the run has no such rows."""
    path = folder / ULTIMATES_NAME
    try:
        frame = pl.read_csv(path)
        rows = (
            frame.filter((pl.col("method") == "chain_ladder") & (pl.col("measure") == "incurred"))
            .group_by(["segment", "line"], maintain_order=True)
            .agg(
                pl.col("paid").sum(),
                pl.col("incurred").sum(),
                pl.col("ultimate").sum(),
                pl.col("ibnr").sum(),
            )
            .sort(["segment", "line"])
        )
    except (OSError, pl.exceptions.PolarsError):
        return []
    return rows.to_dicts()


def summarise_run(folder: Path) -> dict[str, Any]:
    """Everything the result screen shows about a finished run."""
    manifest = _json(folder / MANIFEST_NAME)
    settings = manifest.get("settings", {})
    triangles = settings.get("triangles", {})
    discount = settings.get("discount_used", {})
    outputs = manifest.get("outputs", [])
    profiles = manifest.get("mapping_profiles", [])
    return {
        "run_id": manifest.get("run_id", folder.name),
        "folder": str(folder),
        "date": _stamp(folder / MANIFEST_NAME),
        "version": manifest.get("software", {}).get("actuarycanary"),
        "report": (folder / REPORT_NAME).is_file(),
        "settings": {
            "language": settings.get("language"),
            "currency": settings.get("reporting_currency"),
            "reinsurance": settings.get("bases", {}).get("reinsurance"),
            "value": settings.get("bases", {}).get("value"),
            "currency_view": settings.get("currency_view"),
            "cut_off": triangles.get("cut_off_used"),
            "origin_axis": triangles.get("origin_axis"),
            "origin_period": triangles.get("origin_period"),
            "development_period": triangles.get("development_period"),
            "curve": settings.get("discount", {}).get("curve_id"),
            "discount_available": discount.get("available"),
        },
        "inputs": [
            {
                "name": i.get("name"),
                "concept": i.get("concept"),
                "sheets": [
                    {"name": s.get("name"), "rows": s.get("rows")} for s in i.get("sheets", [])
                ],
            }
            for i in manifest.get("inputs", [])
        ],
        "mappings": [
            {
                "file": p.get("file"),
                "sheet": p.get("sheet"),
                "concept": p.get("concept"),
                "source": p.get("source"),
                "personal_data_dropped": p.get("personal_data_dropped", []),
            }
            for p in profiles
        ],
        "tables_not_used": manifest.get("tables_not_used", []),
        "outputs": len(outputs),
        "headline": headline(folder),
        "findings": findings_summary(folder),
    }
