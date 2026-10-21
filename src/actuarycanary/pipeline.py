"""One run from an input folder to a report and manifest; the command line calls this.

Each step is one component's function: read (io), canonicalise (canonical), convert,
build triangles (structures), estimate (modules.reserving with methods), report, manifest.
"""

from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import polars as pl
from pydantic import BaseModel, ConfigDict, Field

from actuarycanary import __version__
from actuarycanary.canonical.feeds import CanonicalFeed, Finding, canonicalise
from actuarycanary.convert.rates import development_rates
from actuarycanary.io.excel import Workbook, read_workbook
from actuarycanary.manifest.metadata import load_metadata
from actuarycanary.manifest.run import (
    InputRecord,
    OutputRecord,
    SheetRecord,
    SpecRecord,
    run_id,
    write_manifest,
    write_output,
)
from actuarycanary.methods.chain_ladder import ChainLadder
from actuarycanary.modules.reserving import ChainLadderSettings, ReservingResult, run_reserving
from actuarycanary.report.render import REPORT_NAME, ReportContext, render_report
from actuarycanary.spec.loader import load_specs
from actuarycanary.structures.triangles import GROUP_FIELDS, TriangleSettings, build_triangles

REQUIRED_CONCEPT = "claim_valuations"
OPTIONAL_CONCEPTS = ("claims",)
# Specifications whose rules this run applies; recorded with their versions.
SPECS_USED = (
    "claim_valuations",
    "claims",
    "CV01",
    "CV03",
    "CV04",
    "CV06",
    "CV07",
    "MT01",
    "MT02",
    "CL01",
    "CL03",
    "RS01",
    "RS02",
)
TRIANGLES_NAME = "triangles.csv"
ESTIMATES_NAME = "chain_ladder.csv"
FACTORS_NAME = "factors.csv"

Progress = Callable[[str], None]


class InputError(Exception):
    """The input folder cannot be run, for example because a required file is missing."""


class RunSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reporting_currency: str | None = None  # None: project.yaml report.default_reporting_currency
    triangles: TriangleSettings = Field(default_factory=TriangleSettings)
    chain_ladder: ChainLadderSettings = Field(default_factory=ChainLadderSettings)


@dataclass(frozen=True)
class RunResult:
    run_id: str
    folder: Path
    report: Path
    manifest: Path
    reserving: ReservingResult
    findings: tuple[Finding, ...]


def _find_inputs(folder: Path, file_names: dict[str, str]) -> dict[str, Path]:
    if not folder.is_dir():
        raise InputError(f"{folder} is not a folder")
    found = {c: folder / name for c, name in file_names.items() if (folder / name).is_file()}
    if REQUIRED_CONCEPT not in found:
        raise InputError(f"{folder} has no {file_names[REQUIRED_CONCEPT]}; it is required")
    return found


def _input_record(concept: str, workbook: Workbook) -> InputRecord:
    sheets = tuple(SheetRecord(t.sheet, t.frame.height) for t in workbook.tables)
    return InputRecord(concept, workbook.name, workbook.size, workbook.sha256, sheets)


def _settings_record(settings: RunSettings, reporting_currency: str) -> dict[str, Any]:
    record = settings.model_dump(mode="json")
    record["reporting_currency"] = reporting_currency
    record["bases"] = {"reinsurance": "GROSS", "currency": "REPORTING", "value": "NOMINAL"}
    return record


def _write_tables(folder: Path, reserving: ReservingResult) -> list[OutputRecord]:
    """Unrounded data files next to the report (CV06)."""
    cells: list[dict[str, Any]] = []
    estimates: list[dict[str, Any]] = []
    factors: list[dict[str, Any]] = []
    for group in reserving.groups:
        keys = dict(zip(GROUP_FIELDS, group.group, strict=True))
        for measure, triangle in group.triangles.items():
            incremental = triangle.incremental
            for i, origin in enumerate(triangle.origins):
                for j, age in enumerate(triangle.ages):
                    if not triangle.observed[i, j]:
                        continue
                    cells.append(
                        {
                            **keys,
                            "measure": measure,
                            "origin": origin,
                            "development_index": j,
                            "age_months": age,
                            "valuation_date": triangle.valuation_points[triangle.calendar[i, j]],
                            "cumulative": float(triangle.cumulative[i, j]),
                            "incremental": float(incremental[i, j]),
                            "claims": int(triangle.claim_counts[i, j]),
                        }
                    )
        for method, result in group.chain_ladder.items():
            if not isinstance(result, ChainLadder):
                continue
            ages = group.triangles[method].ages
            for j, age in enumerate(ages):
                factors.append(
                    {
                        **keys,
                        "method": f"chain_ladder_{method}",
                        "from_age_months": age,
                        "factor": float(
                            result.factors[j] if j < len(ages) - 1 else result.tail_factor
                        ),
                        "cdf": float(result.cdf[j]),
                    }
                )
        for estimate in group.estimates():
            for method, ultimate in estimate.ultimate.items():
                if ultimate is None:
                    continue
                estimates.append(
                    {
                        **keys,
                        "method": f"chain_ladder_{method}",
                        "origin": estimate.origin,
                        "paid": estimate.paid,
                        "incurred": estimate.incurred,
                        "ultimate": ultimate,
                        "unpaid": estimate.unpaid(method),
                        "ibnr": estimate.ibnr(method),
                    }
                )
    tables = ((TRIANGLES_NAME, cells), (FACTORS_NAME, factors), (ESTIMATES_NAME, estimates))
    return [
        write_output(folder, name, pl.DataFrame(rows, infer_schema_length=None).write_csv())
        for name, rows in tables
    ]


def run(
    folder: Path,
    out_root: Path,
    settings: RunSettings | None = None,
    cache_dir: Path | None = Path(".cache"),
    progress: Progress | None = None,
) -> RunResult:
    """Read `folder`, build triangles and chain ladder, write report and manifest under
    `out_root/<run id>/`."""
    settings = settings or RunSettings()
    step = progress or (lambda _: None)
    metadata = load_metadata()
    specs = load_specs()
    currency = settings.reporting_currency or metadata.report.default_reporting_currency
    file_names = {c: specs.data[c].file_name for c in (REQUIRED_CONCEPT, *OPTIONAL_CONCEPTS)}
    paths = _find_inputs(folder, file_names)

    step("Reading spreadsheets")
    workbooks = {c: read_workbook(p, cache_dir) for c, p in paths.items()}

    step("Checking data against the specifications")
    feeds: dict[str, CanonicalFeed] = {
        c: canonicalise(w.table(), specs.data[c]) for c, w in workbooks.items()
    }

    step("Building triangles")
    claims = feeds["claims"].frame if "claims" in feeds else None
    triangles = build_triangles(
        feeds[REQUIRED_CONCEPT].frame,
        claims,
        settings.triangles,
        development_rates(currency),
        currency,
    )

    step("Running chain ladder")
    reserving = run_reserving(triangles, settings.chain_ladder)

    findings = tuple(f for feed in feeds.values() for f in feed.findings) + triangles.findings
    inputs = [_input_record(c, w) for c, w in workbooks.items()]
    used = [s for s in SPECS_USED if s != "claims" or "claims" in feeds]
    catalogue = {f.spec.id: f.spec for f in specs.files}
    spec_records = [SpecRecord(s, catalogue[s].version, catalogue[s].title_en) for s in used]
    settings_record = _settings_record(settings, currency)
    run = run_id(inputs, spec_records, settings_record, __version__)
    out = out_root / run
    out.mkdir(parents=True, exist_ok=True)

    step("Writing the report")
    context = ReportContext(
        title=metadata.name,
        disclaimer=metadata.report.disclaimer,
        package_version=__version__,
        run_id=run,
        reserving=reserving,
        findings=findings,
        inputs=tuple(inputs),
        specs=tuple(spec_records),
        settings=settings_record,
    )
    outputs = [write_output(out, REPORT_NAME, render_report(context))]
    outputs += _write_tables(out, reserving)

    step("Writing the manifest")
    manifest = write_manifest(
        out,
        run=run,
        package_version=__version__,
        inputs=inputs,
        specs=spec_records,
        settings=settings_record,
        outputs=outputs,
        findings=[asdict(f) for f in findings],
    )
    return RunResult(run, out, out / REPORT_NAME, manifest, reserving, findings)
