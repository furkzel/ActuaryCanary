"""The checks behind the rules of spec/data, evaluated on canonical frames.

A check returns an `Outcome` (rows checked, rows failing, first source references) or None
when the fields it needs were not loaded. It never changes a frame. Rules that the canonical
step already applies (empty keys, duplicates, unmapped labels) are not repeated here; their
findings are turned into outcomes by `from_canonical`.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import polars as pl

from actuarycanary.canonical.feeds import CURRENCY_CODE, Finding
from actuarycanary.convert.market import (
    FX_PERIOD_AVERAGE,
    FX_PERIOD_END,
    FX_SPOT,
    PRICE_INDEX,
    month_of,
)
from actuarycanary.io.excel import SOURCE_COLUMNS, SOURCE_FILE, SOURCE_ROW, SOURCE_SHEET
from actuarycanary.methods.robust_z import MAD_SCALE, MEAN_AD_SCALE, THRESHOLD
from actuarycanary.quality.model import EXAMPLES, Outcome, SourceRef
from actuarycanary.spec.models import DataConceptSpec

EARLIEST_DATE = date(1950, 1, 1)  # DV-CLM-07
PAYMENT_MULTIPLE = 10  # DV-CLV-15
CLOSED = ("CLOSED", "CLOSED_NIL")
AMOUNTS = (
    "paid_to_date",
    "case_reserve",
    "subrogation_to_date",
    "salvage_to_date",
    "expense_allocated_to_date",
    "ceded_paid_to_date",
    "ceded_reserve",
)


@dataclass(frozen=True)
class Context:
    frames: dict[str, pl.DataFrame]
    specs: dict[str, DataConceptSpec]
    cut_off: date | None
    # what the run converts into and restates with (DV-MKT-07); unknown: that rule is not evaluated
    reporting_currency: str | None = None
    price_index: str | None = None
    adjusted: bool = False  # the run restates amounts with the price index (CV02)


Check = Callable[[Context], Outcome | None]


def references(rows: pl.DataFrame) -> tuple[SourceRef, ...]:
    """The first source references of `rows` in file, sheet, row order."""
    first = rows.select(SOURCE_COLUMNS).sort(SOURCE_COLUMNS).head(EXAMPLES)
    return tuple(
        SourceRef(f, s, r)
        for f, s, r in zip(first[SOURCE_FILE], first[SOURCE_SHEET], first[SOURCE_ROW], strict=True)
    )


def _frame(ctx: Context, concept: str, columns: tuple[str, ...]) -> pl.DataFrame | None:
    frame = ctx.frames.get(concept)
    if frame is None or any(c not in frame.columns for c in columns):
        return None
    return frame


def _outcome(rule: str, concept: str, checked: int, failing: pl.DataFrame) -> Outcome:
    return Outcome(rule, concept, checked, failing.height, "", references(failing))


def _rows(
    rule: str,
    concept: str,
    columns: tuple[str, ...],
    bad: pl.Expr,
    applies: pl.Expr | None = None,
) -> Check:
    """Check over single rows: `bad` rows among the rows where `applies` (default all)."""

    def check(ctx: Context) -> Outcome | None:
        frame = _frame(ctx, concept, columns)
        if frame is None:
            return None
        scope = frame if applies is None else frame.filter(applies.fill_null(False))
        return _outcome(rule, concept, scope.height, scope.filter(bad.fill_null(False)))

    return check


def present(rule: str, concept: str, fields: tuple[str, ...]) -> Check:
    return _rows(rule, concept, fields, pl.any_horizontal(pl.col(*fields).is_null()))


def unique(rule: str, concept: str, keys: tuple[str, ...], identical_rows: bool = False) -> Check:
    """Rows repeating an earlier row's key (or, with `identical_rows`, every field)."""

    def check(ctx: Context) -> Outcome | None:
        frame = _frame(ctx, concept, keys)
        if frame is None:
            return None
        columns = [c for c in frame.columns if c not in SOURCE_COLUMNS] if identical_rows else keys
        scope = frame.filter(pl.all_horizontal(pl.col(*keys).is_not_null()))
        repeated = scope.filter(~pl.struct(columns).is_first_distinct())
        return _outcome(rule, concept, scope.height, repeated)

    return check


def iso_currency(rule: str, concept: str) -> Check:
    # shape only: three capital letters (the canonical step uses the same test)
    return _rows(
        rule,
        concept,
        ("currency",),
        ~pl.col("currency").str.contains(CURRENCY_CODE.pattern),
        pl.col("currency").is_not_null() & (pl.col("currency") != "UNKNOWN"),
    )


def in_classes(rule: str, concept: str, fields: tuple[str, ...]) -> Check:
    def check(ctx: Context) -> Outcome | None:
        spec = ctx.specs[concept]
        classes = {f.name: f.classes for f in spec.fields if f.classes}
        frame = ctx.frames.get(concept)
        used = tuple(f for f in fields if f in classes and frame is not None and f in frame.columns)
        if frame is None or not used:
            return None
        bad = pl.any_horizontal(
            *(pl.col(f).is_not_null() & ~pl.col(f).is_in(classes[f]) for f in used)
        )
        return _outcome(rule, concept, frame.height, frame.filter(bad.fill_null(False)))

    return check


def not_below(
    rule: str, concept: str, fields: tuple[str, ...], limit: float, strict: bool = False
) -> Check:
    """Every present value is at least `limit` (greater than it when `strict`)."""

    def check(ctx: Context) -> Outcome | None:
        frame = ctx.frames.get(concept)
        used = [f for f in fields if frame is not None and f in frame.columns]
        if frame is None or not used:
            return None
        below = [(pl.col(f) <= limit) if strict else (pl.col(f) < limit) for f in used]
        return _outcome(
            rule, concept, frame.height, frame.filter(pl.any_horizontal(below).fill_null(False))
        )

    return check


def ordered(rule: str, concept: str, first: str, second: str, strict: bool = False) -> Check:
    """`first` on or before `second` (before it when `strict`), where both are present."""
    bad = (pl.col(first) >= pl.col(second)) if strict else (pl.col(first) > pl.col(second))
    both = pl.col(first).is_not_null() & pl.col(second).is_not_null()
    return _rows(rule, concept, (first, second), bad, both)


def month_end(rule: str, concept: str, field: str) -> Check:
    return _rows(
        rule,
        concept,
        (field,),
        pl.col(field) != pl.col(field).dt.month_end(),
        pl.col(field).is_not_null(),
    )


def in_other(
    rule: str, concept: str, field: str, other: str, other_field: str | None = None
) -> Check:
    """Every present `concept.field` value exists in `other.other_field` (when loaded)."""
    target = other_field or field

    def check(ctx: Context) -> Outcome | None:
        frame = _frame(ctx, concept, (field,))
        reference = _frame(ctx, other, (target,))
        if frame is None or reference is None:
            return None
        scope = frame.filter(pl.col(field).is_not_null())
        known = reference[target].drop_nulls().unique()
        return _outcome(
            rule, concept, scope.height, scope.filter(~pl.col(field).is_in(known.implode()))
        )

    return check


# --- claim valuations --------------------------------------------------------------------


def _claim_steps(frame: pl.DataFrame) -> pl.DataFrame:
    """Each valuation with the claim's previous one (by month), for pair rules."""
    ordered_rows = frame.sort("claim_id", "valuation_date", SOURCE_ROW)
    over = pl.col("claim_id")
    previous = [
        pl.col(c).shift(1).over(over).alias(f"_previous_{c}") for c in AMOUNTS if c in frame.columns
    ]
    previous.append(pl.col("valuation_date").shift(1).over(over).alias("_previous_date"))
    return ordered_rows.with_columns(*previous).filter(pl.col("_previous_date").is_not_null())


def paid_never_decreases(ctx: Context) -> Outcome | None:  # DV-CLV-07
    frame = _frame(ctx, "claim_valuations", ("claim_id", "valuation_date", "paid_to_date"))
    if frame is None:
        return None
    steps = _claim_steps(frame).filter(
        pl.col("paid_to_date").is_not_null() & pl.col("_previous_paid_to_date").is_not_null()
    )
    bad = steps.filter(pl.col("paid_to_date") < pl.col("_previous_paid_to_date"))
    return _outcome("DV-CLV-07", "claim_valuations", steps.height, bad)


def amounts_not_negative(ctx: Context) -> Outcome | None:  # DV-CLV-08
    return not_below("DV-CLV-08", "claim_valuations", AMOUNTS, 0.0)(ctx)


def closed_has_no_reserve(ctx: Context) -> Outcome | None:  # DV-CLV-09
    return _rows(
        "DV-CLV-09",
        "claim_valuations",
        ("status", "case_reserve"),
        pl.col("case_reserve") != 0,
        pl.col("status").is_in(CLOSED) & pl.col("case_reserve").is_not_null(),
    )(ctx)


def nil_has_no_payment(ctx: Context) -> Outcome | None:  # DV-CLV-10
    return _rows(
        "DV-CLV-10",
        "claim_valuations",
        ("status", "paid_to_date"),
        pl.col("paid_to_date") != 0,
        (pl.col("status") == "CLOSED_NIL") & pl.col("paid_to_date").is_not_null(),
    )(ctx)


def ceded_within_gross(ctx: Context) -> Outcome | None:  # DV-CLV-11
    frame = ctx.frames.get("claim_valuations")
    pairs = [
        (c, g)
        for c, g in (("ceded_paid_to_date", "paid_to_date"), ("ceded_reserve", "case_reserve"))
        if frame is not None and c in frame.columns and g in frame.columns
    ]
    if frame is None or not pairs:
        return None
    bad = pl.any_horizontal([pl.col(c) > pl.col(g) for c, g in pairs])
    return _outcome(
        "DV-CLV-11", "claim_valuations", frame.height, frame.filter(bad.fill_null(False))
    )


def one_currency_per_claim(ctx: Context) -> Outcome | None:  # DV-CLV-12
    frame = _frame(ctx, "claim_valuations", ("claim_id", "currency"))
    if frame is None:
        return None
    known = pl.col("currency").filter(pl.col("currency") != "UNKNOWN")
    mixed = frame.filter(known.n_unique().over("claim_id") > 1)
    return _outcome("DV-CLV-12", "claim_valuations", frame.height, mixed)


def no_missing_months(ctx: Context) -> Outcome | None:  # DV-CLV-13
    """Claims with a month missing before they close or before the cut-off."""
    frame = _frame(ctx, "claim_valuations", ("claim_id", "valuation_date", "status"))
    if frame is None:
        return None
    ordered_rows = frame.sort("claim_id", "valuation_date", SOURCE_ROW)
    months = pl.col("valuation_date").dt.year() * 12 + pl.col("valuation_date").dt.month()
    last_month = pl.lit(ctx.cut_off.year * 12 + ctx.cut_off.month) if ctx.cut_off else months.max()
    step = months - months.shift(1).over("claim_id")
    ended = pl.col("status").is_in(CLOSED)
    gap_before = step > 1
    unfinished = (
        (pl.col("claim_id") != pl.col("claim_id").shift(-1)) & ~ended & (months < last_month)
    ).fill_null(True)
    rows = ordered_rows.filter(gap_before.fill_null(False) | unfinished)
    claims = ordered_rows.select(pl.col("claim_id").n_unique()).item()
    gaps = rows.group_by("claim_id", maintain_order=True).first()
    return _outcome("DV-CLV-13", "claim_valuations", claims, gaps)


def claim_exists(ctx: Context) -> Outcome | None:  # DV-CLV-14
    return in_other("DV-CLV-14", "claim_valuations", "claim_id", "claims")(ctx)


def payment_far_above_incurred(ctx: Context) -> Outcome | None:  # DV-CLV-15
    columns = ("claim_id", "valuation_date", "paid_to_date", "case_reserve")
    frame = _frame(ctx, "claim_valuations", columns)
    if frame is None:
        return None
    steps = _claim_steps(frame)
    earlier = pl.col("_previous_paid_to_date") + pl.col("_previous_case_reserve")
    scope = steps.filter((earlier > 0) & pl.col("paid_to_date").is_not_null())
    payment = pl.col("paid_to_date") - pl.col("_previous_paid_to_date")
    bad = scope.filter(payment > PAYMENT_MULTIPLE * earlier)
    return _outcome("DV-CLV-15", "claim_valuations", scope.height, bad)


# --- claims --------------------------------------------------------------------------------


def dates_in_range(ctx: Context) -> Outcome | None:  # DV-CLM-07
    names = ("occurrence_date", "report_date", "close_date")
    frame = ctx.frames.get("claims")
    used = [n for n in names if frame is not None and n in frame.columns]
    if frame is None or not used:
        return None
    upper = ctx.cut_off or date.max
    bad = pl.any_horizontal([(pl.col(n) < EARLIEST_DATE) | (pl.col(n) > upper) for n in used])
    return _outcome("DV-CLM-07", "claims", frame.height, frame.filter(bad.fill_null(False)))


def reported_before_first_valuation(ctx: Context) -> Outcome | None:  # DV-CLM-08
    claims = _frame(ctx, "claims", ("claim_id", "report_date"))
    valuations = _frame(ctx, "claim_valuations", ("claim_id", "valuation_date"))
    if claims is None or valuations is None:
        return None
    first = valuations.group_by("claim_id").agg(pl.col("valuation_date").min().alias("_first"))
    joined = claims.filter(pl.col("report_date").is_not_null()).join(first, on="claim_id")
    bad = joined.filter(pl.col("report_date").dt.month_end() > pl.col("_first"))
    return _outcome("DV-CLM-08", "claims", joined.height, bad)


def policy_exists(ctx: Context) -> Outcome | None:  # DV-CLM-09
    return in_other("DV-CLM-09", "claims", "policy_id", "policies")(ctx)


def occurrence_within_cover(ctx: Context) -> Outcome | None:  # DV-CLM-10
    claims = _frame(ctx, "claims", ("policy_id", "occurrence_date"))
    policies = _frame(ctx, "policies", ("policy_id", "start_date", "end_date"))
    if claims is None or policies is None:
        return None
    cover = policies.select("policy_id", "start_date", "end_date").unique("policy_id")
    joined = claims.filter(pl.col("occurrence_date").is_not_null()).join(cover, on="policy_id")
    bad = joined.filter(
        (pl.col("occurrence_date") < pl.col("start_date"))
        | (pl.col("occurrence_date") > pl.col("end_date"))
    )
    return _outcome("DV-CLM-10", "claims", joined.height, bad)


def claim_has_valuation(ctx: Context) -> Outcome | None:  # DV-CLM-11
    return in_other("DV-CLM-11", "claims", "claim_id", "claim_valuations")(ctx)


# --- policies, premiums, expenses, market -----------------------------------------------------


def cancellation_within_cover(ctx: Context) -> Outcome | None:  # DV-POL-05
    return _rows(
        "DV-POL-05",
        "policies",
        ("cancellation_date", "start_date", "end_date"),
        (pl.col("cancellation_date") < pl.col("start_date"))
        | (pl.col("cancellation_date") > pl.col("end_date")),
        pl.col("cancellation_date").is_not_null(),
    )(ctx)


def premium_policy_exists(ctx: Context) -> Outcome | None:  # DV-PRM-06
    return in_other("DV-PRM-06", "premiums", "policy_id", "policies")(ctx)


def premium_currency_is_policy_currency(ctx: Context) -> Outcome | None:  # DV-PRM-09
    premiums = _frame(ctx, "premiums", ("policy_id", "currency"))
    policies = _frame(ctx, "policies", ("policy_id", "currency"))
    if premiums is None or policies is None:
        return None
    other = policies.select("policy_id", pl.col("currency").alias("_policy_currency")).unique(
        "policy_id"
    )
    joined = premiums.join(other, on="policy_id").filter(
        pl.col("currency").is_not_null() & pl.col("_policy_currency").is_not_null()
    )
    bad = joined.filter(pl.col("currency") != pl.col("_policy_currency"))
    return _outcome("DV-PRM-09", "premiums", joined.height, bad)


def effective_within_cover(ctx: Context) -> Outcome | None:  # DV-PRM-07
    premiums = _frame(ctx, "premiums", ("policy_id", "booking_date", "effective_date"))
    policies = _frame(ctx, "policies", ("policy_id", "start_date", "end_date"))
    if premiums is None or policies is None:
        return None
    cover = policies.select("policy_id", "start_date", "end_date").unique("policy_id")
    joined = premiums.join(cover, on="policy_id").with_columns(
        pl.col("effective_date").fill_null(pl.col("booking_date")).alias("_effective")
    )
    scope = joined.filter(
        pl.col("_effective").is_not_null()
        & pl.col("start_date").is_not_null()
        & pl.col("end_date").is_not_null()
    )
    bad = scope.filter(
        (pl.col("_effective") < pl.col("start_date")) | (pl.col("_effective") > pl.col("end_date"))
    )
    return _outcome("DV-PRM-07", "premiums", scope.height, bad)


# --- market series ---------------------------------------------------------------------------

MONTHLY_KINDS = (FX_PERIOD_AVERAGE, FX_PERIOD_END, PRICE_INDEX)
FX_KINDS = (FX_SPOT, FX_PERIOD_AVERAGE, FX_PERIOD_END)
SERIES_KEY = ["series_id", "kind"]
MARKET_FIELDS = ("series_id", "kind", "date", "value")
MONTH = "_month"


def _month_label(month: int) -> str:
    return f"{month // 12}-{month % 12 + 1:02d}"


def _usable_market(frame: pl.DataFrame, kinds: tuple[str, ...]) -> pl.DataFrame:
    """The rows of `kinds` the conversion can use, with the month index of their date."""
    return frame.filter(
        pl.col("kind").is_in(kinds)
        & pl.col("series_id").is_not_null()
        & pl.col("date").is_not_null()
        & (pl.col("value") > 0)
    ).with_columns(month_of("date").alias(MONTH))


def _month_gaps(present: list[int], first: int, last: int) -> list[int]:
    """The months from `first` to `last` that are not in `present`, in order."""
    have = set(present)
    return [m for m in range(first, last + 1) if m not in have]


def _nearest_row(rows: pl.DataFrame, month: int) -> pl.DataFrame:
    """The latest source row of the closest earlier month of `rows`, else of the closest later."""
    ordered = rows.sort(MONTH, *SOURCE_COLUMNS)
    before = ordered.filter(pl.col(MONTH) < month)
    if before.height:
        return before.filter(pl.col(MONTH) == before[MONTH].max()).tail(1)
    after = ordered.filter(pl.col(MONTH) > month)
    return after.filter(pl.col(MONTH) == after[MONTH].min()).tail(1) if after.height else after


def _listing(what: str, listed: list[str], total: int) -> str:
    if total == 0:
        return ""
    return f"{what}: {', '.join(listed)} ({total} months in all)"


def monthly_series_complete(ctx: Context) -> Outcome | None:  # DV-MKT-06
    frame = _frame(ctx, "market", MARKET_FIELDS)
    if frame is None:
        return None
    rows = _usable_market(frame, MONTHLY_KINDS)
    checked = missing = 0
    neighbours: list[pl.DataFrame] = []
    listed: list[str] = []
    for (series_id, kind), part in rows.group_by(SERIES_KEY, maintain_order=True):
        months = sorted(part[MONTH].unique().to_list())
        gaps = _month_gaps(months, months[0], months[-1])
        checked += months[-1] - months[0] + 1
        missing += len(gaps)
        for gap in gaps[: EXAMPLES - len(neighbours)]:
            neighbours.append(_nearest_row(part, gap))
            listed.append(f"{series_id} {kind} {_month_label(gap)}")
    found = pl.concat(neighbours).unique(SOURCE_COLUMNS) if neighbours else rows.head(0)
    message = _listing("months missing between the first and last month", listed, missing)
    return Outcome("DV-MKT-06", "market", checked, missing, message, references(found))


def _first_dates(ctx: Context) -> pl.DataFrame:
    """Earliest date of any amount per currency, over the feeds that hold amounts (CV01)."""
    parts = []
    for concept, date_field in (
        ("claim_valuations", "valuation_date"),
        ("premiums", "booking_date"),
        ("expenses", "period"),
    ):
        frame = _frame(ctx, concept, ("currency", date_field))
        if frame is not None:
            parts.append(
                frame.filter(pl.col("currency").is_not_null() & pl.col(date_field).is_not_null())
                .group_by("currency")
                .agg(pl.col(date_field).min().alias("first"))
            )
    if not parts:
        return pl.DataFrame(schema={"currency": pl.String, "first": pl.Date})
    return pl.concat(parts).group_by("currency").agg(pl.col("first").min()).sort("currency")


def _month_of_date(day: date) -> int:
    return day.year * 12 + day.month - 1


def series_cover_conversions(ctx: Context) -> Outcome | None:  # DV-MKT-07
    frame = _frame(ctx, "market", MARKET_FIELDS)
    reporting, cut_off = ctx.reporting_currency, ctx.cut_off
    if frame is None or reporting is None or cut_off is None:
        return None
    last = _month_of_date(cut_off)
    firsts = _first_dates(ctx)
    # what the run converts or restates: label, series ids, kinds, first month applied
    needs: list[tuple[str, tuple[str, ...], tuple[str, ...], int]] = [
        (
            f"{currency} into {reporting}",
            (f"{currency}/{reporting}", f"{reporting}/{currency}"),
            FX_KINDS,
            _month_of_date(first),
        )
        for currency, first in firsts.iter_rows()
        if currency not in (reporting, "UNKNOWN")
    ]
    index = ctx.price_index
    if (
        index is not None
        and firsts.height
        and (ctx.adjusted or (frame["series_id"] == index).any())
    ):
        earliest = firsts["first"].min()
        assert isinstance(earliest, date)
        needs.append((f"price index {index}", (index,), (PRICE_INDEX,), _month_of_date(earliest)))
    checked = missing = 0
    neighbours: list[pl.DataFrame] = []
    listed: list[str] = []
    for label, ids, kinds, first in needs:
        if first > last:
            continue
        rows = _usable_market(frame, kinds).filter(pl.col("series_id").is_in(ids))
        gaps = _month_gaps(rows[MONTH].unique().to_list(), first, last)
        checked += last - first + 1
        missing += len(gaps)
        if gaps and len(listed) < EXAMPLES:
            span = _month_label(gaps[0]) + (
                f" to {_month_label(gaps[-1])}" if len(gaps) > 1 else ""
            )
            listed.append(f"{label} {span}")
        for gap in gaps[: EXAMPLES - len(neighbours)]:
            neighbours.append(_nearest_row(rows, gap))
    found = pl.concat(neighbours).unique(SOURCE_COLUMNS) if neighbours else frame.head(0)
    message = _listing("no value for a month a conversion or adjustment needs", listed, missing)
    return Outcome("DV-MKT-07", "market", checked, missing, message, references(found))


def monthly_change_is_reasonable(ctx: Context) -> Outcome | None:  # DV-MKT-08
    frame = _frame(ctx, "market", MARKET_FIELDS)
    if frame is None:
        return None
    rows = _usable_market(frame, (*FX_KINDS, PRICE_INDEX))
    # one value per series, kind and month: the latest date, then the latest source row
    monthly = (
        rows.sort("date", *SOURCE_COLUMNS)
        .group_by([*SERIES_KEY, MONTH], maintain_order=True)
        .last()
        .sort([*SERIES_KEY, MONTH])
    )
    log_value = pl.col("value").log()
    steps = monthly.with_columns(
        (log_value - log_value.shift(1).over(SERIES_KEY)).alias("_y"),
        (pl.col(MONTH) - pl.col(MONTH).shift(1).over(SERIES_KEY)).alias("_step"),
    ).filter(pl.col("_step") == 1)
    d = pl.col("_y") - pl.col("_y").median().over(SERIES_KEY)
    mad = d.abs().median().over(SERIES_KEY)
    mean_ad = d.abs().mean().over(SERIES_KEY)
    z = (  # the formula of MT08
        pl.when(mad > 0)
        .then(MAD_SCALE * d / mad)
        .when(mean_ad > 0)
        .then(d / (MEAN_AD_SCALE * mean_ad))
        .otherwise(0.0)
    )
    scored = steps.with_columns(z.alias("_z"))
    flagged = scored.filter(pl.col("_z").abs() > THRESHOLD)
    return _outcome("DV-MKT-08", "market", scored.height, flagged)


CHECKS: dict[str, Check] = {
    "DV-CLV-07": paid_never_decreases,
    "DV-CLV-08": amounts_not_negative,
    "DV-CLV-09": closed_has_no_reserve,
    "DV-CLV-10": nil_has_no_payment,
    "DV-CLV-11": ceded_within_gross,
    "DV-CLV-12": one_currency_per_claim,
    "DV-CLV-13": no_missing_months,
    "DV-CLV-14": claim_exists,
    "DV-CLV-15": payment_far_above_incurred,
    "DV-CLM-04": ordered("DV-CLM-04", "claims", "occurrence_date", "report_date"),
    "DV-CLM-05": ordered("DV-CLM-05", "claims", "report_date", "close_date"),
    "DV-CLM-07": dates_in_range,
    "DV-CLM-08": reported_before_first_valuation,
    "DV-CLM-09": policy_exists,
    "DV-CLM-10": occurrence_within_cover,
    "DV-CLM-11": claim_has_valuation,
    "DV-POL-01": present("DV-POL-01", "policies", ("policy_id",)),
    "DV-POL-02": unique("DV-POL-02", "policies", ("policy_id",)),
    "DV-POL-03": present(
        "DV-POL-03", "policies", ("start_date", "end_date", "segment", "line", "currency")
    ),
    "DV-POL-04": ordered("DV-POL-04", "policies", "start_date", "end_date", strict=True),
    "DV-POL-05": cancellation_within_cover,
    "DV-POL-06": iso_currency("DV-POL-06", "policies"),
    "DV-POL-07": in_classes("DV-POL-07", "policies", ("segment", "channel")),
    "DV-POL-08": not_below("DV-POL-08", "policies", ("sum_insured", "exposure_units"), 0.0),
    "DV-PRM-01": present("DV-PRM-01", "premiums", ("transaction_id", "policy_id")),
    "DV-PRM-02": unique("DV-PRM-02", "premiums", ("transaction_id",)),
    "DV-PRM-03": present("DV-PRM-03", "premiums", ("booking_date", "amount", "currency", "type")),
    "DV-PRM-04": in_classes("DV-PRM-04", "premiums", ("type",)),
    "DV-PRM-05": iso_currency("DV-PRM-05", "premiums"),
    "DV-PRM-06": premium_policy_exists,
    "DV-PRM-07": effective_within_cover,
    "DV-PRM-09": premium_currency_is_policy_currency,
    "DV-EXP-01": present("DV-EXP-01", "expenses", ("period", "amount", "type")),
    "DV-EXP-02": iso_currency("DV-EXP-02", "expenses"),
    "DV-EXP-03": in_classes("DV-EXP-03", "expenses", ("type", "segment")),
    "DV-EXP-04": month_end("DV-EXP-04", "expenses", "period"),
    "DV-EXP-05": not_below("DV-EXP-05", "expenses", ("amount",), 0.0, strict=True),
    "DV-EXP-06": unique("DV-EXP-06", "expenses", ("period", "amount", "type"), identical_rows=True),
    "DV-MKT-01": present("DV-MKT-01", "market", ("series_id", "date", "value", "kind")),
    "DV-MKT-02": unique("DV-MKT-02", "market", ("series_id", "kind", "date")),
    "DV-MKT-03": not_below("DV-MKT-03", "market", ("value",), 0.0, strict=True),
    "DV-MKT-05": in_classes("DV-MKT-05", "market", ("kind",)),
    "DV-MKT-06": monthly_series_complete,
    "DV-MKT-07": series_cover_conversions,
    "DV-MKT-08": monthly_change_is_reasonable,
}

# Rules the canonical step applies while it builds the feed; its findings are the evidence.
CANONICAL_RULES: dict[str, tuple[str, ...]] = {
    "claim_valuations": (
        "DV-CLV-01",
        "DV-CLV-02",
        "DV-CLV-03",
        "DV-CLV-04",
        "DV-CLV-05",
        "DV-CLV-06",
    ),
    "claims": ("DV-CLM-01", "DV-CLM-02", "DV-CLM-03", "DV-CLM-06"),
    "market": ("DV-MKT-01", "DV-MKT-02", "DV-MKT-03", "DV-MKT-04", "DV-MKT-05"),
    "premiums": (
        "DV-PRM-01",
        "DV-PRM-02",
        "DV-PRM-03",
        "DV-PRM-04",
        "DV-PRM-05",
        "DV-PRM-08",
    ),
    "policies": (
        "DV-POL-01",
        "DV-POL-02",
        "DV-POL-03",
        "DV-POL-04",
        "DV-POL-05",
        "DV-POL-06",
        "DV-POL-07",
        "DV-POL-08",
    ),
}
CAST_RULE = "CV07"  # a value that is not the field's type; reported by the canonical step


def from_canonical(concept: str, findings: tuple[Finding, ...], raw: pl.DataFrame) -> list[Outcome]:
    """Outcomes of the rules the canonical step applied; `raw` is the table it started from."""
    rows = raw.height
    found = [f for f in findings if f.concept == concept]
    outcomes = []
    for rule in (*CANONICAL_RULES.get(concept, ()), CAST_RULE):
        hits = [f for f in found if f.rule == rule]
        if not hits:
            outcomes.append(Outcome(rule, concept, rows, 0))
        for hit in hits:
            refs = references(raw.filter(pl.col(SOURCE_ROW).is_in(hit.rows)))
            outcomes.append(Outcome(rule, concept, rows, hit.count, hit.message, refs))
    return outcomes
