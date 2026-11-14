"""Reinsurance measures on the treaty application (M08, MT21, CV09; record 0406):
RI03 ceded share by treaty, RI04 reinsurance result ratio, RI05 loss ratio volatility gross
and net.
"""

import math

import numpy as np
import polars as pl

from actuarycanary.convert.allocation import APPROXIMATION
from actuarycanary.convert.bases import BasisUnavailableError, ReinsuranceBasis
from actuarycanary.measures.claim_amounts import CONCEPT, prepared
from actuarycanary.measures.claim_base import amounts_at, left_out
from actuarycanary.measures.common import group_agg
from actuarycanary.measures.model import (
    NOTE,
    VALUE,
    Basis,
    Computed,
    CurrencyView,
    MeasureInputs,
    MeasureRequest,
    Missing,
)
from actuarycanary.measures.port import NotAvailable
from actuarycanary.measures.premium_measures import earned_rolled
from actuarycanary.modules.reinsurance import ReinsuranceRun, reinsurance_run
from actuarycanary.spec.models import MeasureSpec
from actuarycanary.structures.periods import Period
from actuarycanary.structures.premium import CEDED_TYPE, PremiumError

TREATIES = "reinsurance_treaties"
MOVEMENTS = "reinsurance_transactions"
NO_TREATIES = "no reinsurance treaties were loaded"
INCURRED_VIEW = "incurred view: no ceded ultimate is selected, ceded incurred is used"
RI03_GRAIN = "RI03 is shown per treaty and treaty year; the treaty's scope sets its lines"
QS_TOLERANCE = 0.005  # RI03 edge case: a quota share's claims share against its cession
MIN_ORIGINS = 5  # RI05 edge case


def _run(inputs: MeasureInputs) -> ReinsuranceRun | Missing:
    run = reinsurance_run(inputs)
    return Missing(NO_TREATIES) if run is None else run


def _refs(run: ReinsuranceRun, frame: pl.DataFrame) -> pl.DataFrame:
    return frame.join(
        run.treaty_refs.rename({"refs": f"refs_{TREATIES}"}),
        on=["treaty_id", "inception_date"],
        how="left",
    )


def ceded_share_by_treaty(
    spec: MeasureSpec, inputs: MeasureInputs, request: MeasureRequest
) -> Computed | Missing:
    """RI03: reported ceded incurred and ceded premium of each treaty and treaty year over the
    gross amounts in its scope (claims at the cut-off, written premium)."""
    run = _run(inputs)
    if isinstance(run, Missing):
        return run
    table = run.treaty_table()
    approximated = set()
    if run.allocation is not None:
        cells = run.allocation.rows.filter(pl.col("method") == APPROXIMATION)
        approximated = {
            (t, y) for t, y in cells.select("treaty_id", "origin_year").unique().iter_rows()
        }
    rows: list[dict[str, object]] = []
    for r in table.iter_rows(named=True):
        base = {
            "treaty": r["treaty_id"],
            "treaty_type": r["treaty_type"],
            "treaty_year": r["treaty_year"],
            "treaty_id": r["treaty_id"],
            "inception_date": r["inception_date"],
        }
        for side, top, bottom in (
            ("claims", r.get("reported_ceded_incurred"), r.get("gross_incurred")),
            ("premium", r.get("reported_ceded_premium"), r.get("gross_written")),
        ):
            notes: list[str] = []
            value = None
            top = 0.0 if top is None else float(top)
            if bottom is None or not bottom or bottom <= 0:
                notes.append("gross in scope is zero: not computed")
            else:
                value = top / bottom
                if top == 0:
                    notes.append("no ceded bookings")
            if (r["treaty_id"], r["treaty_year"]) in approximated and side == "claims":
                notes.append(APPROXIMATION)
            share = r.get("cession_share")
            if (
                side == "claims"
                and value is not None
                and r["treaty_type"] == "QUOTA_SHARE"
                and share is not None
                and abs(value - share * r["placed_share"]) > QS_TOLERANCE
            ):
                notes.append(f"differs from the cession share {share:.1%} by more than 0.5 points")
            rows.append(
                {
                    **base,
                    "side": side,
                    "numerator": top,
                    "denominator": bottom,
                    VALUE: value,
                    NOTE: "; ".join(notes),
                }
            )
    frame = pl.DataFrame(rows, infer_schema_length=None)
    if frame.height == 0:
        return Missing("no treaty section could be applied")
    frame = _refs(run, frame).drop("treaty_id", "inception_date")
    keys = ["treaty", "treaty_type", "treaty_year", "side"]
    return Computed(
        frame.select(*keys, pl.exclude(keys)).sort(keys),
        (f"index clause: {run.settings.index_clause}",),
        (TREATIES,),
    )


def _year(column: str) -> pl.Expr:
    return pl.col(column).cast(pl.String).str.slice(0, 4).cast(pl.Int64, strict=False)


def reinsurance_result_ratio(
    spec: MeasureSpec, inputs: MeasureInputs, request: MeasureRequest
) -> Computed | Missing:
    """RI04: (ceded incurred + commission earned - ceded premium earned - reinstatement
    premium) over gross earned premium, per origin year, on the incurred view."""
    run = _run(inputs)
    if isinstance(run, Missing):
        return run
    if not (inputs.feeds["premiums"]["type"] == CEDED_TYPE).any():
        return Missing("no ceded premium in the premium file (CV03)")
    currency = request.basis.currency
    ceded_basis = Basis(ReinsuranceBasis.CEDED, currency)
    try:
        ceded, notes = amounts_at(inputs, ceded_basis, "incurred", [inputs.cut_off])
    except BasisUnavailableError as error:
        return Missing(str(error))
    ceded, left = left_out(ceded, "incurred")
    by_origin = MeasureRequest(("origin_period",), Period.YEAR, ceded_basis)
    ceded, dim_notes = prepared(ceded, inputs, by_origin)
    claims = group_agg(ceded, ["origin_period"], [pl.col(VALUE).sum().alias("ceded_incurred")])
    calendar = MeasureRequest(("calendar_period",), Period.YEAR, ceded_basis)
    gross_calendar = MeasureRequest(
        ("calendar_period",), Period.YEAR, Basis(ReinsuranceBasis.GROSS, currency)
    )
    try:
        ceded_premium, more = earned_rolled(inputs, calendar)
        gross_premium, _ = earned_rolled(inputs, gross_calendar)
        commission, _ = (
            earned_rolled(inputs, gross_calendar, transaction_types=("RI_COMMISSION",))
            if (inputs.feeds["premiums"]["type"] == "RI_COMMISSION").any()
            else (ceded_premium.head(0), [])
        )
    except PremiumError as error:
        return Missing(str(error))
    premium = (
        gross_premium.select(
            _year("calendar_period").alias("year"), pl.col(VALUE).alias("gross_earned")
        )
        .join(
            ceded_premium.select(
                _year("calendar_period").alias("year"), pl.col(VALUE).alias("ceded_premium_earned")
            ),
            on="year",
            how="left",
        )
        .join(
            commission.select(
                _year("calendar_period").alias("year"), pl.col(VALUE).alias("commission_earned")
            ),
            on="year",
            how="left",
        )
    )
    reinstatement = _reinstatement_by_year(run)
    years = {s.inception.year for s in run.inputs.sections}
    frame = (
        claims.with_columns(_year("origin_period").alias("year"))
        .join(premium, on="year", how="full", coalesce=True)
        .join(reinstatement, on="year", how="left")
        .with_columns(
            pl.col("ceded_incurred").fill_null(0.0),
            pl.col("ceded_premium_earned").fill_null(0.0),
            pl.col("commission_earned").fill_null(0.0),
            pl.col("reinstatement_premium").fill_null(0.0),
            pl.coalesce("origin_period", pl.col("year").cast(pl.String)).alias("origin_period"),
        )
        .with_columns(
            (
                pl.col("ceded_incurred")
                + pl.col("commission_earned")
                - pl.col("ceded_premium_earned")
                - pl.col("reinstatement_premium")
            ).alias("numerator"),
            pl.col("gross_earned").alias("denominator"),
        )
    )
    in_force = pl.col("year").is_in(sorted(years))
    frame = frame.with_columns(
        pl.when(in_force & (pl.col("denominator") > 0))
        .then(pl.col("numerator") / pl.col("denominator"))
        .alias(VALUE),
        pl.when(~in_force)
        .then(pl.lit("no treaty was in force in this origin year: not computed"))
        .when(pl.col("denominator").fill_null(0) <= 0)
        .then(pl.lit("gross earned premium is zero: not computed"))
        .otherwise(pl.lit(INCURRED_VIEW))
        .alias(NOTE),
    ).filter(pl.col("year").is_not_null())
    keep = [
        "origin_period",
        VALUE,
        NOTE,
        "numerator",
        "denominator",
        "ceded_incurred",
        "commission_earned",
        "ceded_premium_earned",
        "reinstatement_premium",
        f"refs_{CONCEPT}",
    ]
    frame = frame.select([c for c in keep if c in frame.columns]).sort("origin_period")
    return Computed(frame, (INCURRED_VIEW, *notes, *left, *dim_notes, *more), (CONCEPT,))


def _reinstatement_by_year(run: ReinsuranceRun) -> pl.DataFrame:
    """Reinstatement premium booked, by origin year of the cells it was allocated to, in the
    reporting currency at the cut-off rate."""
    empty = pl.DataFrame(schema={"year": pl.Int64, "reinstatement_premium": pl.Float64})
    if run.allocation is None:
        return empty
    rows = run.allocation.rows.filter(
        (pl.col("type") == "REINSTATEMENT_PREMIUM") & pl.col("origin_year").is_not_null()
    )
    if rows.height == 0:
        return empty
    rate = run._rate(rows, "currency", run.reporting_currency)
    return (
        rows.with_columns((pl.col("amount") * rate).alias("amount"))
        .group_by(pl.col("origin_year").alias("year"))
        .agg(pl.col("amount").sum().alias("reinstatement_premium"))
    )


def net_loss_ratio_volatility(
    spec: MeasureSpec, inputs: MeasureInputs, request: MeasureRequest
) -> Computed | Missing:
    """RI05: standard deviation over origin years of the ultimate loss ratio gross and net of
    the loaded programme (MT21), and their ratio, per segment and line."""
    run = _run(inputs)
    if isinstance(run, Missing):
        return run
    frame, notes = volatility_frame(inputs, net_share_by_origin(run, inputs))
    if frame.height == 0:
        return Missing("no segment and line with ultimate loss ratios")
    return Computed(frame, tuple(notes), ())


def net_share_by_origin(run: ReinsuranceRun, inputs: MeasureInputs) -> pl.DataFrame:
    """Net over gross incurred at the cut-off of the programme's application, per segment,
    line and origin year (the claim-level ultimates of MT21 are the incurred times the origin's
    development, so the share carries over to the ultimate)."""
    schema = {"segment": pl.String, "line": pl.String, "year": pl.Int64, "net_share": pl.Float64}
    app, book = run.application, run.inputs.book
    if app is None or book is None or "occurrence_date" not in book.claims.columns:
        return pl.DataFrame(schema=schema)
    latest = (
        app.net.filter(pl.col("valuation_date") <= inputs.cut_off)
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
        pl.col("occurrence_date").dt.year().cast(pl.Int64).alias("year"),
    )
    joined = latest.join(claims, on="claim_id", how="left")
    rate = run._rate(joined, "currency", run.reporting_currency)
    return (
        joined.with_columns(
            (pl.col("gross_incurred") * rate).alias("g"), (pl.col("net_incurred") * rate).alias("n")
        )
        .group_by(["segment", "line", "year"])
        .agg(pl.col("g").sum(), pl.col("n").sum())
        .filter(pl.col("g") > 0)
        .select("segment", "line", "year", (pl.col("n") / pl.col("g")).alias("net_share"))
        .cast(schema)  # type: ignore[arg-type]
    )


def volatility_frame(
    inputs: MeasureInputs, net_share: pl.DataFrame
) -> tuple[pl.DataFrame, list[str]]:
    """Gross and net ultimate loss ratios per segment, line and origin year, and their sample
    standard deviations over the origin years (RI05)."""
    notes: list[str] = []
    gross = Basis(ReinsuranceBasis.GROSS, CurrencyView.REPORTING)
    table = inputs.methods.measure("RS02", gross.label())
    view = "ultimate"
    if isinstance(table, NotAvailable) or "method" not in table.columns:
        ultimates = None
        view = "incurred"
        notes.append("no selected ultimate: the incurred at the cut-off is used (incurred view)")
    else:
        ultimates = table.filter(pl.col("method") == "selected").select(
            "segment",
            "line",
            _year("origin_period").alias("year"),
            pl.col("ultimate").alias("gross_loss"),
        )
    if ultimates is None:
        try:
            states, _ = amounts_at(inputs, gross, "incurred", [inputs.cut_off])
        except BasisUnavailableError as error:
            return pl.DataFrame(), [str(error)]
        states, _ = prepared(
            states, inputs, MeasureRequest(("segment", "line", "origin_period"), Period.YEAR, gross)
        )
        ultimates = group_agg(
            states, ["segment", "line", "origin_period"], [pl.col(VALUE).sum().alias("gross_loss")]
        ).select("segment", "line", _year("origin_period").alias("year"), "gross_loss")
    try:
        premium, _ = earned_rolled(
            inputs, MeasureRequest(("segment", "line", "calendar_period"), Period.YEAR, gross)
        )
    except PremiumError as error:
        return pl.DataFrame(), [f"earned premium: {error}"]
    premium = premium.select(
        "segment", "line", _year("calendar_period").alias("year"), pl.col(VALUE).alias("earned")
    )
    origins = (
        ultimates.join(premium, on=["segment", "line", "year"], how="inner")
        .join(net_share, on=["segment", "line", "year"], how="left")
        .filter(pl.col("gross_loss").is_not_null() & (pl.col("earned") > 0))
        .with_columns(
            (pl.col("gross_loss") / pl.col("earned")).alias("gross_lr"),
            (pl.col("gross_loss") * pl.col("net_share").fill_null(1.0) / pl.col("earned")).alias(
                "net_lr"
            ),
        )
    )
    rows: list[dict[str, object]] = []
    for (segment, line), part in origins.sort("year").group_by(
        ["segment", "line"], maintain_order=True
    ):
        years = part["year"].to_list()
        row: dict[str, object] = {
            "segment": segment,
            "line": line,
            "origin_years": ", ".join(str(y) for y in years),
            "loss_view": view,
            "numerator": None,
            "denominator": None,
            VALUE: None,
            NOTE: "",
        }
        if len(years) < MIN_ORIGINS:
            row[NOTE] = f"fewer than {MIN_ORIGINS} origin years: not computed"
        else:
            gross_sd = float(np.std(part["gross_lr"].to_numpy(), ddof=1))
            net_sd = float(np.std(part["net_lr"].to_numpy(), ddof=1))
            row["numerator"], row["denominator"] = net_sd, gross_sd
            if gross_sd > 0 and math.isfinite(gross_sd):
                row[VALUE] = net_sd / gross_sd
            else:
                row[NOTE] = "gross standard deviation is zero: ratio not computed"
        rows.append(row)
    frame = pl.DataFrame(rows, infer_schema_length=None) if rows else pl.DataFrame()
    return frame, notes
