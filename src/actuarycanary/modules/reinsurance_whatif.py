"""MT21 what-if: the loaded programme, an alternative written in the assumptions register, or
both side by side, compared on cost and on the volatility of the net loss ratio (record 0408).

An alternative is a set of register entries of method MT21: `scope` is the name of the
programme, `target` the treaty_id, `name` a field of reinsurance_treaties and `value` its
value (the entry style of the other methods; no new file format). A treaty of the alternative
without inception_date and expiry_date takes the contract periods of the loaded programme;
`line` may list several lines separated by commas. The rows then pass the same rules as the
loaded treaties (sections_from_frame), so an alternative without the terms of its type is left
out and named. Gross figures never change: only the programme does.
"""

from dataclasses import dataclass, replace
from datetime import date

import numpy as np
import polars as pl

from actuarycanary.convert.bases import ReinsuranceBasis
from actuarycanary.measures.model import Basis, CurrencyView, MeasureInputs
from actuarycanary.measures.port import NotAvailable
from actuarycanary.measures.reinsurance_programme import net_share_by_origin, volatility_frame
from actuarycanary.methods.assumptions import AssumptionsRegister
from actuarycanary.methods.reinsurance.application import Application, apply_programme
from actuarycanary.methods.reinsurance.premium import apply_premium
from actuarycanary.methods.reinsurance.terms import Excluded, Section, sections_from_frame
from actuarycanary.modules.reinsurance import ReinsuranceRun

METHOD = "MT21"
LOADED = "loaded"
DATE_FIELDS = ("inception_date", "expiry_date")
NUMBER_FIELDS = (
    "cession_share",
    "retention",
    "limit",
    "number_of_lines",
    "aggregate_deductible",
    "aggregate_limit",
    "reinstatements",
    "reinstatement_rate",
    "placed_share",
    "premium_rate",
    "ceding_commission",
)
TEXT_FIELDS = (
    "treaty_type",
    "attachment_basis",
    "loss_basis",
    "segment",
    "entity",
    "currency",
    "index_series",
)


@dataclass(frozen=True)
class Programme:
    name: str
    sections: list[Section]
    excluded: list[Excluded]


def alternatives(register: AssumptionsRegister, loaded: list[Section]) -> list[Programme]:
    """The alternative programmes of the register, by name."""
    entries = [e for e in register.entries if e.method == METHOD]
    names = sorted({e.scope for e in entries})
    periods = sorted({(s.inception, s.expiry) for s in loaded})
    currency = loaded[0].currency if loaded else None
    out: list[Programme] = []
    for name in names:
        rows: list[dict[str, object]] = []
        for treaty in sorted({e.target for e in entries if e.scope == name}):
            fields: dict[str, object] = {}
            for e in entries:
                if e.scope != name or e.target != treaty:
                    continue
                if e.name in NUMBER_FIELDS:
                    fields[e.name] = None if e.value is None else float(e.value)
                elif e.name in DATE_FIELDS:
                    fields[e.name] = None if e.value is None else date.fromisoformat(str(e.value))
                else:
                    fields[e.name] = e.value
            fields.setdefault("currency", currency)
            spans = (
                [(fields["inception_date"], fields["expiry_date"])]
                if fields.get("inception_date") and fields.get("expiry_date")
                else periods
            )
            lines = [x.strip() for x in str(fields.get("line") or "").split(",") if x.strip()]
            for inception, expiry in spans:
                for line in lines or [None]:
                    rows.append(
                        {
                            **{k: fields.get(k) for k in (*NUMBER_FIELDS, *TEXT_FIELDS)},
                            "treaty_id": treaty,
                            "inception_date": inception,
                            "expiry_date": expiry,
                            "line": line,
                        }
                    )
        schema = {
            **{k: pl.Float64 for k in NUMBER_FIELDS},
            **{k: pl.String for k in (*TEXT_FIELDS, "treaty_id", "line")},
            **{k: pl.Date for k in DATE_FIELDS},
        }
        sections, excluded = sections_from_frame(pl.DataFrame(rows, schema=schema))
        out.append(Programme(name, sections, excluded))
    return out


def _ultimate_factor(inputs: MeasureInputs) -> pl.DataFrame | None:
    """Selected ultimate over incurred per segment, line and origin year (MT21 assumption:
    claim-level ultimates are the incurred times this factor)."""
    table = inputs.methods.measure(
        "RS02", Basis(ReinsuranceBasis.GROSS, CurrencyView.REPORTING).label()
    )
    if isinstance(table, NotAvailable) or "method" not in table.columns:
        return None
    return (
        table.filter((pl.col("method") == "selected") & (pl.col("incurred") > 0))
        .select(
            "segment",
            "line",
            pl.col("origin_period").cast(pl.String).str.slice(0, 4).cast(pl.Int64).alias("year"),
            (pl.col("ultimate") / pl.col("incurred")).alias("factor"),
            ((pl.col("ultimate") - pl.col("incurred")) / pl.col("ultimate")).alias("ibnr_share"),
        )
        .drop_nulls("factor")
    )


def _claim_losses(
    run: ReinsuranceRun, app: Application, factor: pl.DataFrame | None
) -> pl.DataFrame:
    """Gross, ceded and net incurred per claim at the cut-off in the reporting currency, with
    the ultimate factor of its origin."""
    book = run.inputs.book
    assert book is not None
    latest = (
        app.net.filter(pl.col("valuation_date") <= run.cut_off)
        .sort("valuation_date")
        .group_by("claim_id")
        .last()
    )
    claims = book.claims.select(
        "claim_id",
        *[
            pl.col(c) if c in book.claims.columns else pl.lit(None, dtype=pl.String).alias(c)
            for c in ("segment", "line", "currency")
        ],
        pl.col("occurrence_date").dt.year().cast(pl.Int64).alias("year")
        if "occurrence_date" in book.claims.columns
        else pl.lit(None, dtype=pl.Int64).alias("year"),
    )
    joined = latest.join(claims, on="claim_id", how="left")
    rate = run._rate(joined, "currency", run.reporting_currency)
    joined = joined.with_columns(
        (pl.col("gross_incurred") * rate).alias("gross"),
        (pl.col("ceded_incurred") * rate).alias("ceded"),
    )
    if factor is None:
        return joined.with_columns(
            pl.lit(1.0).alias("factor"), pl.lit(None, dtype=pl.Float64).alias("ibnr_share")
        )
    return joined.join(factor, on=["segment", "line", "year"], how="left").with_columns(
        pl.col("factor").fill_null(1.0)
    )


def comparison(
    inputs: MeasureInputs, run: ReinsuranceRun, register: AssumptionsRegister
) -> tuple[pl.DataFrame, list[str]]:
    """programme_comparison.csv: one row per programme (record 0408)."""
    settings = run.settings
    notes: list[str] = []
    programmes: list[Programme] = []
    if settings.programme in (LOADED, "both"):
        programmes.append(Programme(LOADED, run.inputs.sections, run.inputs.excluded))
    if settings.programme in ("alternative", "both"):
        found = alternatives(register, run.inputs.sections)
        if not found:
            notes.append("no alternative programme in the assumptions register (method MT21)")
        programmes += found
    factor = _ultimate_factor(inputs) if settings.loss_view == "ultimate" else None
    if settings.loss_view == "ultimate" and factor is None:
        notes.append("no selected ultimate: the incurred view is used")
    rows: list[dict[str, object]] = []
    book = run.inputs.book
    for programme in programmes:
        if book is None:
            break
        if programme.name == LOADED and run.application is not None:
            app = run.application
            premium = run.inputs.premium
            results = app.sections
        else:
            premium = (
                apply_premium(
                    programme.sections,
                    run.inputs.written,
                    price_index=run.inputs.options.price_index,
                    fx=run.inputs.options.fx,
                    facultative_shares=run.inputs.options.facultative_shares,
                )
                if run.inputs.written is not None
                else None
            )
            options = replace(
                run.inputs.options,
                earned_premium=premium.earned_premium() if premium else {},
                deposit_premium=premium.deposit_premium() if premium else {},
            )
            app = apply_programme(programme.sections, book, options, programme.excluded)
            results = app.sections
        losses = _claim_losses(run, app, factor)
        gross = float((losses["gross"] * losses["factor"]).sum())
        ceded = float((losses["ceded"] * losses["factor"]).sum())
        by_section = premium.by_section if premium is not None else None
        ceded_premium = (
            float(by_section["ceded_premium"].fill_null(0).sum())
            if by_section is not None
            else None
        )
        commission = (
            float(by_section["commission"].fill_null(0).sum()) if by_section is not None else None
        )
        reinstatement = float(sum(r.reinstatement_premium or 0.0 for r in results))
        frame, _ = volatility_frame(
            inputs, net_share_by_origin(replace(run, application=app), inputs)
        )
        ratios = frame[["value"]].drop_nulls()["value"].to_numpy() if frame.height else np.array([])
        rows.append(
            {
                "programme": programme.name,
                "treaties": len({s.treaty_id for s in programme.sections}),
                "left_out": "; ".join(f"{e.treaty_id}: {e.reason}" for e in programme.excluded),
                "loss_view": "ultimate" if factor is not None else "incurred",
                "gross_loss": gross,
                "expected_ceded_loss": ceded,
                "net_loss": gross - ceded,
                "ceded_premium": ceded_premium,
                "commission": commission,
                "reinstatement_premium": reinstatement,
                "net_result": None
                if ceded_premium is None
                else ceded + (commission or 0.0) - ceded_premium - reinstatement,
                "volatility_ratio_lines": len(ratios),
                "volatility_ratio_mean": float(ratios.mean()) if len(ratios) else None,
                "currency": run.reporting_currency,
            }
        )
    return pl.DataFrame(rows, infer_schema_length=None), notes
