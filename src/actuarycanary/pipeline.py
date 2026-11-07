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
from pydantic import BaseModel, ConfigDict, Field, field_validator

from actuarycanary import __version__
from actuarycanary.canonical.amounts import INCREMENTAL, TO_DATE
from actuarycanary.canonical.feeds import CanonicalError, CanonicalFeed, Finding, canonicalise
from actuarycanary.convert.bases import ValueBasis
from actuarycanary.convert.market import ConversionError, MarketData
from actuarycanary.convert.rates import DevelopmentRates, development_rates
from actuarycanary.convert.views import (
    ORIGINAL,
    UNIT_LABEL,
    VIEWS,
    identity_rates,
    split_claims,
    split_policies,
)
from actuarycanary.io.excel import RawTable, Workbook, read_workbooks, spreadsheets
from actuarycanary.manifest.metadata import load_metadata
from actuarycanary.manifest.run import (
    InputRecord,
    OutputRecord,
    SheetRecord,
    SpecRecord,
    run_id,
    write_manifest,
    write_output,
    write_parquet_table,
    write_table,
)
from actuarycanary.measures.lineage import DEFAULT_FORMAT, FORMATS, build_lineage
from actuarycanary.measures.model import Basis, CurrencyView, MeasureInputs, with_refs
from actuarycanary.measures.output import values_table
from actuarycanary.methods import diagnostics as diagnostic_limits
from actuarycanary.methods import isolation_forest, robust_z
from actuarycanary.methods import registry as tier_b_registry
from actuarycanary.methods.assumptions import AssumptionsRegister, records
from actuarycanary.methods.chain_ladder import ChainLadder
from actuarycanary.methods.seeding import RUN_SEED
from actuarycanary.methods.selection import BF_BELOW_MATURITY
from actuarycanary.methods.severity import LargeLossError, LargeLossSettings, parse_large_loss
from actuarycanary.modules import reserving_tier_b_output as tier_b_output
from actuarycanary.modules import severity_run
from actuarycanary.modules.anomalies import AnomalyResult, run_anomalies
from actuarycanary.modules.methods_port import ReservingPort
from actuarycanary.modules.output import analysis_json
from actuarycanary.modules.premium_input import earned_premium_by_origin
from actuarycanary.modules.reserving import (
    SELECTION_MEASURE,
    ChainLadderSettings,
    MethodInputs,
    ReservingResult,
    earlier_result,
    methods_run,
    not_run_notes,
    run_reserving,
)
from actuarycanary.modules.reserving_output import (
    ANOMALIES_NAME,
    ASSUMPTIONS_NAME,
    CASH_FLOWS_NAME,
    DIAGNOSTICS_NAME,
    RANGE_NAME,
    ULTIMATES_NAME,
    anomalies_csv,
    assumptions_csv,
    cash_flows_csv,
    diagnostics_csv,
    range_csv,
    ultimates_csv,
)
from actuarycanary.modules.runner import AnalysisResult, run_modules
from actuarycanary.modules.tier_b_inputs import TierBInputs, tier_b_source
from actuarycanary.quality.engine import evaluate
from actuarycanary.quality.model import QualityReport
from actuarycanary.quality.output import QUALITY_NAME, quality_json
from actuarycanary.recognition.amounts import detect_amounts
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
from actuarycanary.report import language
from actuarycanary.report.model import ReportInputs, build_model, earlier_valuation
from actuarycanary.report.modules_section import render_modules_section
from actuarycanary.report.quality_section import render_quality_section
from actuarycanary.report.render import REPORT_NAME, render_report
from actuarycanary.spec.loader import load_specs
from actuarycanary.structures.triangles import (
    GROUP_FIELDS,
    OriginAxis,
    TriangleError,
    TriangleSet,
    TriangleSettings,
    build_triangles,
    resolve_cut_off,
)

REQUIRED_CONCEPT = "claim_valuations"
OPTIONAL_CONCEPTS = ("claims",)
MARKET = "market"
POLICIES = "policies"
# Read, checked for the quality report and used by the measures; market and policies also feed
# the triangles when a setting asks for them.
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
MEASURES_NAME = "measures.csv"
MODULES_NAME = "modules.json"

Progress = Callable[[str], None]
# Shown the sheets whose layout has no saved profile; returns them accepted, edited or skipped.
Confirm = Callable[[list[tuple[TableRecognition, RawTable]], Dictionary], list[TableRecognition]]


class InputError(Exception):
    """The input folder cannot be run, for example because a required file is missing."""


class RunSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reporting_currency: str | None = None  # None: project.yaml report.default_reporting_currency
    # Read market data and convert foreign currencies into the reporting currency (CV01)
    # whenever the folder has a market sheet (decision 0052, reverses 0034). Off: only amounts
    # already in the reporting currency are used, the rest is reported apart; the
    # inflation-adjusted basis always reads market data.
    use_market: bool = True
    # How `lineage.csv` is written (decision 0222): 1, one line per value, file and sheet with
    # row ranges; 2, atoms of rows listed once in `lineage_atoms.csv`. The files differ, so the
    # format is part of the run id.
    lineage_format: int = DEFAULT_FORMAT
    # The language of report.html: "en" (default) or "tr" (record 0224). The other outputs and
    # the terminal stay English. The report differs, so the language enters the run id.
    language: str = "en"
    # REPORTING (default) converts every amount into the reporting currency (CV01); ORIGINAL
    # converts nothing and keeps each line apart per currency (record 0225). Part of the run id.
    currency_view: str = "REPORTING"
    triangles: TriangleSettings = Field(default_factory=TriangleSettings)
    chain_ladder: ChainLadderSettings = Field(default_factory=ChainLadderSettings)
    # the judgements of the user: selected factors, exclusions, priors, future inflation,
    # overrides (record 0037); part of the settings, so of the run id
    assumptions: AssumptionsRegister = Field(default_factory=AssumptionsRegister)

    @field_validator("currency_view")
    @classmethod
    def _known_currency_view(cls, value: str) -> str:
        if value not in VIEWS:
            raise ValueError(
                f"currency view {value!r} is unknown; known: reporting and original "
                "(FUNCTIONAL equals REPORTING in version 1.0, CV01)"
            )
        return value

    @field_validator("language")
    @classmethod
    def _known_language(cls, value: str) -> str:
        if value not in language.LANGUAGES:
            raise ValueError(f"report language {value!r} is unknown; known: en and tr")
        return value

    @field_validator("lineage_format")
    @classmethod
    def _known_lineage_format(cls, value: int) -> int:
        if value not in FORMATS:
            raise ValueError(f"lineage format {value} is unknown; known: 1 and 2")
        return value


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
    analysis: AnalysisResult
    anomalies: AnomalyResult
    report_data: dict[str, Any]  # every number and text of the report page (golden test)
    severity: severity_run.SeverityRun  # MT17 and MT18 over the claim sizes


def recognise_folder(
    folder: Path, dictionary: Dictionary, cache_dir: Path | None, profiles_dir: Path | None
) -> list[LoadedTable]:
    """Read every spreadsheet in `folder`, recognise every sheet, apply saved profiles."""
    if not folder.is_dir():
        raise InputError(f"{folder} is not a folder")
    loaded: list[LoadedTable] = []
    for workbook in read_workbooks(spreadsheets(folder), cache_dir):
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
            rec = detect_amounts(rec, table)
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


def _amounts(items: list[LoadedTable]) -> str:
    """Whether the sheets of a concept hold amounts to date or per period; they must agree."""
    kinds = {i.recognition.amounts for i in items}
    if len(kinds) > 1:
        raise InputError(
            "the claim_valuations sheets disagree about their amounts (cumulative to date or "
            "per period): "
            + "; ".join(f"{i.recognition.label}: {i.recognition.amounts}" for i in items)
        )
    return next(iter(kinds), TO_DATE)


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
        **(
            {"amounts": rec.amounts, "amounts_note": rec.amounts_note}
            if rec.concept == "claim_valuations"
            else {}
        ),
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


def _settings_record(
    settings: RunSettings,
    reporting_currency: str,
    price_index: str,
    market_read: bool,
    large_loss: LargeLossSettings,
) -> dict[str, Any]:
    record = settings.model_dump(mode="json")
    record["reporting_currency"] = reporting_currency
    record["triangles"]["price_index"] = price_index
    record["methods"] = _methods_record()
    # the seeds and defaults of the tier B and severity methods, and the large-loss section of
    # project.yaml, so that a change of any of them gives another run id (records 0281, 0620)
    record["tier_b"] = tier_b_registry.settings(RUN_SEED)
    record["severity"] = severity_run.settings()
    record["large_loss"] = large_loss.manifest_record()
    record["bases"] = {
        "reinsurance": settings.triangles.reinsurance_basis.value,
        "currency": settings.currency_view,
        "currency_conversion": "market"
        if market_read and settings.currency_view != ORIGINAL
        else "none",
        "value": settings.triangles.value_basis.value,
    }
    return record


def _with_cut_off_used(record: dict[str, Any], cut_off: date) -> dict[str, Any]:
    """The settings record with the cut-off actually used next to the `cut_off` setting, and
    the dates that default to it."""
    triangles = dict(record["triangles"])
    triangles["cut_off_used"] = cut_off.isoformat()
    if triangles["value_basis"] == ValueBasis.INFLATION_ADJUSTED.value:
        triangles["value_date_used"] = triangles["value_date"] or cut_off.isoformat()
    if record["bases"]["currency_conversion"] == "market":
        triangles["development_rate_date_used"] = (
            triangles["development_rate_date"] or cut_off.isoformat()
        )
    return {**record, "triangles": triangles}


def _rate_findings(rates: DevelopmentRates) -> list[Finding]:
    """CV01 notes on the constant development rates: fallbacks used and currencies left out."""
    notes = [
        Finding(
            "claim_valuations",
            "CV01",
            "INFO",
            1,
            f"development rate of {currency} taken from {flag}",
        )
        for currency, flag in sorted(rates.flags.items())
    ]
    if rates.missing:
        notes.append(
            Finding(
                "claim_valuations",
                "CV01",
                "WARNING",
                len(rates.missing),
                "no development rate for " + ", ".join(rates.missing) + ": not converted",
            )
        )
    return notes


def _earned_premium(
    specs: Any,
    inputs: MeasureInputs,
    axis: OriginAxis,
    cache: dict[Any, Any],
    view: CurrencyView = CurrencyView.REPORTING,
) -> tuple[pl.DataFrame | None, str]:
    """Earned premium per segment, line and origin period for the premium-based methods, from
    PR02 on the basis of the run; the measure is kept in `cache` for the module runner."""
    if axis is not OriginAxis.ACCIDENT:
        return None, (
            "the premium-based methods need accident or underwriting origins matched to earned "
            f"premium, and the origin axis is {axis.value}"
        )
    settings = inputs.triangles.settings if inputs.triangles else TriangleSettings()
    frame, reason, measure = earned_premium_by_origin(
        specs,
        inputs,
        settings.origin_period,
        settings.reinsurance_basis,
        settings.value_basis,
        view,
    )
    if measure is not None:
        request, result = measure
        cache[(result.measure, request)] = result
    return frame, reason


def _other_value_basis(
    valuations: pl.DataFrame,
    claims: pl.DataFrame | None,
    policies: pl.DataFrame | None,
    market: MarketData | None,
    settings: RunSettings,
    rates: DevelopmentRates,
    currency: str,
    price_index: str,
    triangles: TriangleSet,
) -> tuple[TriangleSet | None, str]:
    """The paid triangles on the other value basis, for the inflation-adjusted chain ladder
    (MT07), which needs the same claims restated and not restated. None, with the reason,
    when the market data has no price index or the triangles cannot be built."""
    if market is None:
        return None, "no market data (exchange rates and a price index) was loaded"
    if market.index(price_index) is None:
        return None, f"the price index {price_index} is not in the market data"
    adjusted = settings.triangles.value_basis is ValueBasis.INFLATION_ADJUSTED
    other = settings.triangles.model_copy(
        update={"value_basis": ValueBasis.NOMINAL if adjusted else ValueBasis.INFLATION_ADJUSTED}
    )
    try:
        return (
            build_triangles(
                valuations,
                claims,
                other,
                rates,
                currency,
                policies=policies,
                market=market,
                price_index=price_index,
                measures=("paid",),
            ),
            "",
        )
    except (ConversionError, TriangleError) as error:
        return None, f"the triangles on the other value basis could not be built: {error}"


def _methods_record() -> dict[str, Any]:
    """The fixed settings of the methods, part of the manifest and the run id: a change of a
    threshold in the code gives another run id."""
    return {
        "selection_measure": SELECTION_MEASURE,
        "bf_below_maturity": BF_BELOW_MATURITY,
        "diagnostics": {
            "thin_evidence_origins": diagnostic_limits.THIN_EVIDENCE_ORIGINS,
            "late_development_factor": diagnostic_limits.LATE_DEVELOPMENT_FACTOR,
            "few_link_ratios": diagnostic_limits.FEW_LINK_RATIOS,
        },
        "robust_z": {
            "threshold": robust_z.THRESHOLD,
            "min_group_size": robust_z.MIN_GROUP_SIZE,
            "group_by": list(robust_z.GROUP_BY),
        },
        "isolation_forest": {
            "n_estimators": isolation_forest.N_ESTIMATORS,
            "max_samples": isolation_forest.MAX_SAMPLES,
            "contamination": isolation_forest.CONTAMINATION,
            "min_group_size": isolation_forest.MIN_GROUP_SIZE,
            "seed": isolation_forest.SEED,
        },
    }


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
    try:
        large_loss = parse_large_loss(metadata.large_loss)
    except LargeLossError as error:
        raise InputError(f"project.yaml: {error}") from error
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
    adjusted = settings.triangles.value_basis is ValueBasis.INFLATION_ADJUSTED
    wanted = [REQUIRED_CONCEPT, *OPTIONAL_CONCEPTS]
    if settings.use_market or adjusted:
        wanted.append(MARKET)
    if settings.triangles.origin_axis is OriginAxis.UNDERWRITING:
        wanted.append(POLICIES)
    if adjusted and MARKET not in by_concept:
        name = specs.data[MARKET].file_name
        raise InputError(
            f"{folder}: the inflation-adjusted basis needs a price index and exchange rates, "
            f"but no sheet was recognised as {MARKET} (for example {name})"
        )
    concepts = [c for c in wanted if c in by_concept]
    market_read = MARKET in concepts

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
        feeds[concept] = canonicalise(combined, specs.data[concept], _amounts(by_concept[concept]))
    checked = dict(feeds)
    unreadable: dict[str, str] = {}
    for concept in CHECKED_CONCEPTS:
        if concept not in by_concept or concept in feeds:
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
        if t.recognition.concept not in concepts and t.recognition.concept not in checked
    ]

    step("Building triangles")
    original = settings.currency_view == ORIGINAL
    if original and adjusted:
        raise InputError(
            "the inflation-adjusted basis restates amounts in the reporting currency and cannot "
            "be combined with the ORIGINAL currency view"
        )
    valuations = feeds[REQUIRED_CONCEPT].frame
    claims = feeds["claims"].frame if "claims" in feeds else None
    policies = feeds[POLICIES].frame if POLICIES in feeds else None
    measure_frames = {c: f.frame for c, f in checked.items()}
    currencies = valuations["currency"].drop_nulls().unique().to_list()
    if original:
        # nothing is converted and no line adds currencies: a line per currency (record 0225)
        if claims is not None:
            claims = split_claims(claims, valuations)
            measure_frames["claims"] = claims
        if policies is not None:
            policies = split_policies(policies)
        if POLICIES in measure_frames:
            measure_frames[POLICIES] = split_policies(measure_frames[POLICIES])
        currency = UNIT_LABEL
    market = MarketData.from_frame(feeds[MARKET].frame) if MARKET in feeds else None
    price_index = settings.triangles.price_index or metadata.report.default_price_index
    rates = (
        identity_rates(currencies)
        if original
        else development_rates(
            currency,
            currencies,
            market,
            settings.triangles.development_rate_date
            or resolve_cut_off(valuations, settings.triangles),
        )
    )
    triangles = build_triangles(
        valuations,
        claims,
        settings.triangles,
        rates,
        currency,
        policies=policies,
        market=market,
        price_index=price_index,
    )

    sources = {c: tuple(i.recognition.label for i in by_concept[c]) for c in checked}
    quality = evaluate(
        specs,
        checked,
        raw_tables,
        sources,
        triangles.cut_off,
        unreadable,
        reporting_currency=None if original else currency,
        price_index=price_index,
        adjusted=adjusted,
    )
    rate_notes = tuple(_rate_findings(rates)) if market is not None and not adjusted else ()
    findings = (
        tuple(f for feed in feeds.values() for f in feed.findings) + rate_notes + triangles.findings
    )
    measure_inputs = MeasureInputs(
        feeds=with_refs(measure_frames),
        cut_off=triangles.cut_off,
        reporting_currency=currency,
        rates=rates,
        market=market,
        price_index=price_index,
        value_date=settings.triangles.value_date,
        fiscal_year_start_month=settings.triangles.fiscal_year_start_month,
        origin_axis=settings.triangles.origin_axis.value,
        triangles=triangles,
        large_loss_percentile=large_loss.percentile,
        large_loss_thresholds=large_loss.thresholds,
    )
    reinsurance, value_basis = settings.triangles.reinsurance_basis, settings.triangles.value_basis
    period = settings.triangles.origin_period
    cache: dict[Any, Any] = {}

    step("Running the reserving methods")
    view = CurrencyView.ORIGINAL if original else CurrencyView.REPORTING
    premium, premium_reason = _earned_premium(
        specs, measure_inputs, settings.triangles.origin_axis, cache, view
    )
    if original:
        other_value, other_reason = (
            None,
            "the other value basis is restated in the reporting currency: not built in the "
            "ORIGINAL currency view",
        )
    else:
        other_value, other_reason = _other_value_basis(
            valuations, claims, policies, market, settings, rates, currency, price_index, triangles
        )
    method_inputs = MethodInputs(
        register=settings.assumptions,
        premium=premium,
        premium_reason=premium_reason,
        adjusted=triangles if adjusted else other_value,
        nominal=other_value if adjusted else triangles,
        adjusted_reason=other_reason,
        origin_axis=settings.triangles.origin_axis.value,
        tier_b=TierBInputs(
            tier_b_source(
                valuations,
                claims,
                measure_frames.get(POLICIES),
                settings.triangles,
                rates,
                currency,
                policies=policies,
                market=market,
                price_index=price_index,
                cut_off=triangles.cut_off,
            )
        ),
    )
    reserving = run_reserving(triangles, settings.chain_ladder, method_inputs)

    step("Fitting claim sizes and extreme values")
    severity = severity_run.run_severity(measure_inputs, settings.assumptions)
    measure_inputs.extreme_value_note = severity.comparison
    reserving = replace(reserving, extra_assumptions=severity.entries)

    step("Flagging anomalies")
    anomalies = run_anomalies(valuations, claims, rates, triangles.cut_off)

    step("Computing measures and running modules")
    basis_label = Basis(reinsurance, CurrencyView.REPORTING, value_basis).label()
    measure_inputs.methods = ReservingPort(reserving, basis_label, frozenset({"MT08", "MT09"}))
    analysis = run_modules(
        specs,
        measure_inputs,
        quality,
        period,
        reinsurance,
        value_basis,
        cache=cache,
        notes={
            "M03": severity.notes.get("M03", ()),
            "M04": not_run_notes(reserving),
            "M06": [*anomalies.reasons, *severity.notes.get("M06", ())],
        },
        view=view,
    )
    checked_only = [c for c in CHECKED_CONCEPTS if c in checked]
    inputs = _input_records(
        [*concepts, *[c for c in checked_only if c not in concepts]], by_concept
    )
    extra = ["CV02"] if adjusted else []
    ran = [
        i
        for module in sorted(specs.modules.values(), key=lambda m: m.id)
        for i in (module.id, *module.measures)
    ]
    ran_methods = [
        *methods_run(reserving),
        "MT08",
        "MT09",
        *severity_run.methods_run(severity),
        *tier_b_output.measures_run(reserving),
    ]
    used = [
        s
        for s in (*SPECS_USED, *extra, *concepts, *checked_only, *ran, *ran_methods)
        if s != "claims" or "claims" in feeds
    ]
    used = list(dict.fromkeys([*used, specs.finding_rules.id]))
    catalogue = {f.spec.id: f.spec for f in specs.files}
    spec_records = [SpecRecord(s, catalogue[s].version, catalogue[s].title_en) for s in used]
    settings_record = _settings_record(settings, currency, price_index, market_read, large_loss)
    applied = [
        {
            "file": m["file"],
            "sheet": m["sheet"],
            "concept": m["concept"],
            "columns": m["columns"],
            # only per-period amounts are named, so cumulative ones keep the id they had
            **({"amounts": INCREMENTAL} if m.get("amounts") == INCREMENTAL else {}),
        }
        for m in mappings
    ]
    run = run_id(inputs, spec_records, settings_record, __version__, applied)
    out = out_root / run
    out.mkdir(parents=True, exist_ok=True)
    # the resolved cut-off is recorded next to the setting; it follows from the inputs and
    # settings already in the run id, so it is not an input to the id (record 0023)
    settings_used = _with_cut_off_used(settings_record, triangles.cut_off)

    step("Writing the tables")
    outputs = [write_output(out, QUALITY_NAME, quality_json(quality))]
    outputs += _write_tables(out, reserving)
    results = analysis.results()
    assert analysis.inputs is not None
    outputs.append(write_output(out, MEASURES_NAME, values_table(results).write_csv()))
    lineage = build_lineage(results, analysis.inputs, settings.lineage_format)
    for name, text in lineage.files().items():
        outputs.append(write_output(out, name, text))
    outputs.append(write_output(out, MODULES_NAME, analysis_json(analysis, reserving)))
    in_force = reserving.assumptions()
    for name, content in (
        (ASSUMPTIONS_NAME, assumptions_csv(in_force)),
        (ULTIMATES_NAME, ultimates_csv(reserving)),
        (RANGE_NAME, range_csv(reserving)),
        (CASH_FLOWS_NAME, cash_flows_csv(reserving)),
        (
            DIAGNOSTICS_NAME,
            diagnostics_csv(reserving, severity_run.diagnostic_rows(severity)),
        ),
        (ANOMALIES_NAME, anomalies_csv(anomalies)),
    ):
        outputs.append(write_output(out, name, content))
    for name, table in tier_b_output.tables(reserving).items():
        outputs.append(write_table(out, name, table))
    for name, table in tier_b_output.distribution_frames(reserving).items():
        outputs.append(write_parquet_table(out, name, table))
    for name, table in severity.files().items():
        outputs.append(write_table(out, name, table))
    randomness = [
        {"method": "MT09", "seed": isolation_forest.SEED, "purpose": "isolation forest"},
        *[row for row in tier_b_registry.randomness(RUN_SEED) if row["method"] in ran_methods],
        *severity.randomness(),
    ]

    step("Writing the report")
    previous = earlier_valuation(reserving)
    with language.using(settings.language):
        report_data = build_model(
            ReportInputs(
                metadata=metadata,
                run_id=run,
                package_version=__version__,
                catalogue=specs,
                reserving=reserving,
                earlier=None if previous is None else earlier_result(reserving, previous),
                analysis=analysis,
                quality=quality,
                anomalies=anomalies,
                data_findings=findings,
                inputs=tuple(inputs),
                specs=tuple(spec_records),
                settings=settings_used,
                outputs=tuple(outputs),
                lineage=lineage.summary(),
                randomness=tuple(randomness),
                mappings=tuple(mappings),
            )
        )
    with language.using(settings.language):
        page = render_report(
            report_data,
            quality_html=render_quality_section(quality, catalogue["DQ01"].version, specs),
            modules_html=render_modules_section(analysis, specs),
        )
    outputs.insert(0, write_output(out, REPORT_NAME, page))

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
        lineage_format=lineage.format,
        findings=[asdict(f) for f in findings],
        assumptions=records(in_force),
        randomness=randomness,
    )
    tables = tuple(t.recognition for t in loaded)
    return RunResult(
        run,
        out,
        out / REPORT_NAME,
        manifest,
        reserving,
        findings,
        tables,
        quality,
        analysis,
        anomalies,
        report_data,
        severity,
    )
