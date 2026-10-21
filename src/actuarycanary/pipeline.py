"""One run from an input folder to a report and manifest; the command line calls this.

Each step is one component's function: read (io), recognise (recognition), canonicalise
(canonical), convert, build triangles (structures), estimate (modules.reserving with
methods), report, manifest. Every spreadsheet in the folder is read and every sheet
recognised; file names are hints only.
"""

from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
from pydantic import BaseModel, ConfigDict, Field

from actuarycanary import __version__
from actuarycanary.canonical.feeds import CanonicalError, CanonicalFeed, Finding, canonicalise
from actuarycanary.convert.rates import development_rates
from actuarycanary.io.excel import RawTable, Workbook, read_workbook, spreadsheets
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
from actuarycanary.quality.engine import evaluate
from actuarycanary.quality.model import QualityReport
from actuarycanary.quality.output import QUALITY_NAME, quality_json
from actuarycanary.recognition.dictionary import Dictionary, build_dictionary
from actuarycanary.recognition.mapping_profiles import (
    load_profile,
    profile_sha256,
    save_profile,
)
from actuarycanary.recognition.tables import (
    Source,
    TableRecognition,
    canonical_table,
    recognise_table,
    to_profile,
    with_profile,
)
from actuarycanary.recognition.values import ValueMapping
from actuarycanary.report.quality_section import render_quality_section
from actuarycanary.report.render import REPORT_NAME, ReportContext, render_report
from actuarycanary.spec.loader import load_specs
from actuarycanary.structures.triangles import GROUP_FIELDS, TriangleSettings, build_triangles

REQUIRED_CONCEPT = "claim_valuations"
OPTIONAL_CONCEPTS = ("claims",)
# Read and checked for the quality report only; no analysis uses them yet.
CHECKED_CONCEPTS = ("policies", "premiums", "expenses", "market")
# Specifications whose rules this run applies; recorded with their versions.
SPECS_USED = (
    "claim_valuations",
    "claims",
    "AL01",
    "AL02",
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
    "DQ01",
)
TRIANGLES_NAME = "triangles.csv"
ESTIMATES_NAME = "chain_ladder.csv"
FACTORS_NAME = "factors.csv"

Progress = Callable[[str], None]
# Shown the sheets whose layout has no saved profile; returns them accepted, edited or skipped.
Confirm = Callable[[list[tuple[TableRecognition, RawTable]], Dictionary], list[TableRecognition]]


class InputError(Exception):
    """The input folder cannot be run, for example because a required file is missing."""


class RunSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reporting_currency: str | None = None  # None: project.yaml report.default_reporting_currency
    triangles: TriangleSettings = Field(default_factory=TriangleSettings)
    chain_ladder: ChainLadderSettings = Field(default_factory=ChainLadderSettings)


@dataclass(frozen=True)
class LoadedTable:
    workbook: Workbook
    table: RawTable
    recognition: TableRecognition


@dataclass(frozen=True)
class RunResult:
    run_id: str
    folder: Path
    report: Path
    manifest: Path
    reserving: ReservingResult
    findings: tuple[Finding, ...]
    tables: tuple[TableRecognition, ...]
    quality: QualityReport


def recognise_folder(
    folder: Path, dictionary: Dictionary, cache_dir: Path | None, profiles_dir: Path | None
) -> list[LoadedTable]:
    """Read every spreadsheet in `folder`, recognise every sheet, apply saved profiles."""
    if not folder.is_dir():
        raise InputError(f"{folder} is not a folder")
    loaded: list[LoadedTable] = []
    for path in spreadsheets(folder):
        workbook = read_workbook(path, cache_dir)
        for table in workbook.tables:
            if not table.headers:
                continue
            rec = recognise_table(table, workbook.name, dictionary)
            saved = (
                None
                if rec.source is Source.CANONICAL
                else load_profile(profiles_dir, rec.fingerprint)
            )
            if saved is not None:
                rec = with_profile(rec, saved[0], saved[1], dictionary)
            loaded.append(LoadedTable(workbook, table, rec))
    return loaded


def _confirm(
    loaded: list[LoadedTable],
    dictionary: Dictionary,
    confirm: Confirm | None,
    profiles_dir: Path | None,
    today: date,
) -> list[LoadedTable]:
    """Ask about every layout without a saved profile; save what was confirmed."""
    pending = [i for i, t in enumerate(loaded) if t.recognition.source is Source.AUTOMATIC]
    if not pending or confirm is None:
        return loaded
    answers = confirm([(loaded[i].recognition, loaded[i].table) for i in pending], dictionary)
    result = list(loaded)
    for i, rec in zip(pending, answers, strict=True):
        source = Source.SKIPPED if rec.concept is None else Source.CONFIRMED
        rec = replace(rec, source=source)
        if profiles_dir is not None:
            profile = to_profile(rec, today)
            save_profile(profiles_dir, profile)
            rec = replace(rec, profile_sha256=profile_sha256(profile))
        result[i] = replace(loaded[i], recognition=rec)
    return result


def _combined(parts: list[RawTable]) -> RawTable:
    """Sheets of one concept as one table (for example market series over several sheets)."""
    if len(parts) == 1:
        return parts[0]
    frame = pl.concat([p.frame for p in parts], how="diagonal_relaxed")
    return RawTable(" + ".join(p.sheet for p in parts), frame)


def _input_records(
    concepts: list[str], by_concept: dict[str, list[LoadedTable]]
) -> list[InputRecord]:
    """One record per file and concept used, in concept order."""
    records: list[InputRecord] = []
    for concept in concepts:
        seen: set[str] = set()
        for item in by_concept[concept]:
            workbook = item.workbook
            if workbook.name in seen:
                continue
            seen.add(workbook.name)
            sheets = tuple(SheetRecord(t.sheet, t.frame.height) for t in workbook.tables)
            records.append(
                InputRecord(concept, workbook.name, workbook.size, workbook.sha256, sheets)
            )
    return records


def _mapping_record(rec: TableRecognition, values: list[ValueMapping]) -> dict[str, Any]:
    return {
        "file": rec.file,
        "sheet": rec.sheet,
        "concept": rec.concept,
        "header_row": rec.header_row,
        "rows_above_header": rec.rows_above,
        "fingerprint": rec.fingerprint,
        "source": str(rec.source),
        "profile_sha256": rec.profile_sha256,
        "columns": [[m.source, m.field] for m in rec.mappings if m.used],
        "layers": [str(m.layer) for m in rec.mappings if m.used],
        "columns_not_used": [m.source for m in rec.mappings if not m.used and not m.personal],
        "personal_data_dropped": [m.source for m in rec.mappings if m.personal],
        "unmapped_labels": [
            {"field": v.field, "label": label, "rows": rows}
            for v in values
            for label, rows in v.unmapped
        ],
    }


def _settings_record(settings: RunSettings, reporting_currency: str) -> dict[str, Any]:
    record = settings.model_dump(mode="json")
    record["reporting_currency"] = reporting_currency
    record["bases"] = {"reinsurance": "GROSS", "currency": "REPORTING", "value": "NOMINAL"}
    return record


def _with_cut_off_used(record: dict[str, Any], cut_off: date) -> dict[str, Any]:
    """The settings record with the cut-off actually used next to the `cut_off` setting."""
    triangles = dict(record["triangles"])
    triangles["cut_off_used"] = cut_off.isoformat()
    return {**record, "triangles": triangles}


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
    profiles_dir: Path | None = None,
    confirm: Confirm | None = None,
    today: date | None = None,
) -> RunResult:
    """Read `folder`, build triangles and chain ladder, write report and manifest under
    `out_root/<run id>/`.

    Sheets are recognised by content. Layouts with a profile in `profiles_dir` are read with
    it; others are passed to `confirm`, and what it returns is saved as profiles. Without
    `confirm` the proposals are used as they are and nothing is saved.
    """
    settings = settings or RunSettings()
    step = progress or (lambda _: None)
    metadata = load_metadata()
    specs = load_specs()
    dictionary = build_dictionary(specs)
    currency = settings.reporting_currency or metadata.report.default_reporting_currency

    step("Reading and recognising spreadsheets")
    loaded = recognise_folder(folder, dictionary, cache_dir, profiles_dir)
    loaded = _confirm(loaded, dictionary, confirm, profiles_dir, today or date.today())
    by_concept: dict[str, list[LoadedTable]] = {}
    for item in loaded:
        if item.recognition.concept is not None:
            by_concept.setdefault(item.recognition.concept, []).append(item)
    if REQUIRED_CONCEPT not in by_concept:
        name = specs.data[REQUIRED_CONCEPT].file_name
        raise InputError(
            f"{folder}: no sheet was recognised as {REQUIRED_CONCEPT} (for example {name}); "
            "it is required"
        )
    concepts = [c for c in (REQUIRED_CONCEPT, *OPTIONAL_CONCEPTS) if c in by_concept]

    step("Checking data against the specifications")
    feeds: dict[str, CanonicalFeed] = {}
    raw_tables: dict[str, pl.DataFrame] = {}
    mappings: list[dict[str, Any]] = []
    for concept in concepts:
        parts: list[RawTable] = []
        for item in by_concept[concept]:
            raw, values = canonical_table(item.table, item.recognition, dictionary)
            parts.append(raw)
            mappings.append(_mapping_record(item.recognition, values))
        combined = _combined(parts)
        raw_tables[concept] = combined.frame
        feeds[concept] = canonicalise(combined, specs.data[concept])
    checked = dict(feeds)
    unreadable: dict[str, str] = {}
    for concept in CHECKED_CONCEPTS:
        if concept not in by_concept:
            continue
        parts = [
            canonical_table(i.table, i.recognition, dictionary)[0] for i in by_concept[concept]
        ]
        combined = _combined(parts)
        try:
            checked[concept] = canonicalise(combined, specs.data[concept])
            raw_tables[concept] = combined.frame
        except CanonicalError as error:
            unreadable[concept] = str(error)
    not_used = [
        {"file": t.recognition.file, "sheet": t.recognition.sheet, "concept": t.recognition.concept}
        for t in loaded
        if t.recognition.concept not in concepts
    ]

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

    sources = {c: tuple(i.recognition.label for i in by_concept[c]) for c in checked}
    quality = evaluate(specs, checked, raw_tables, sources, triangles.cut_off, unreadable)
    findings = tuple(f for feed in feeds.values() for f in feed.findings) + triangles.findings
    inputs = _input_records(concepts, by_concept)
    used = [s for s in SPECS_USED if s != "claims" or "claims" in feeds]
    used += [c for c in CHECKED_CONCEPTS if c in checked]
    catalogue = {f.spec.id: f.spec for f in specs.files}
    spec_records = [SpecRecord(s, catalogue[s].version, catalogue[s].title_en) for s in used]
    settings_record = _settings_record(settings, currency)
    applied = [
        {"file": m["file"], "sheet": m["sheet"], "concept": m["concept"], "columns": m["columns"]}
        for m in mappings
    ]
    run = run_id(inputs, spec_records, settings_record, __version__, applied)
    out = out_root / run
    out.mkdir(parents=True, exist_ok=True)
    # the resolved cut-off is recorded next to the setting; it follows from the inputs and
    # settings already in the run id, so it is not an input to the id (record 0023)
    settings_used = _with_cut_off_used(settings_record, triangles.cut_off)

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
        settings=settings_used,
        quality_html=render_quality_section(quality, catalogue["DQ01"].version),
    )
    outputs = [write_output(out, REPORT_NAME, render_report(context))]
    outputs.append(write_output(out, QUALITY_NAME, quality_json(quality)))
    outputs += _write_tables(out, reserving)

    step("Writing the manifest")
    manifest = write_manifest(
        out,
        run=run,
        package_version=__version__,
        inputs=inputs,
        mapping_profiles=mappings,
        tables_not_used=not_used,
        specs=spec_records,
        settings=settings_used,
        outputs=outputs,
        findings=[asdict(f) for f in findings],
    )
    tables = tuple(t.recognition for t in loaded)
    return RunResult(run, out, out / REPORT_NAME, manifest, reserving, findings, tables, quality)
