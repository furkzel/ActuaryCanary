"""Checks of the feeds built by F1bc: reinsurance treaties (DV-RTY), reinsurance transactions
(DV-RTR), recoveries (DV-RCV) and the ledger (DV-LDG). The rules that decide which rows enter a
feed are applied by the canonical step; the rules here list rows and leave them as they are.

A rule that compares two feeds runs when both are loaded; `NEEDS` names the other feeds so that
the quality report can say which one is missing (record 0384).
"""

import polars as pl

from actuarycanary.canonical.recoveries import (
    AMOUNT_TOLERANCE,
    cumulative_at,
    recovery_differences,
    to_date_fields,
)
from actuarycanary.io.excel import SOURCE_COLUMNS, SOURCE_ROW
from actuarycanary.quality.checks import (
    Check,
    Context,
    _frame,
    _outcome,
    _rows,
    in_other,
    iso_currency,
    references,
)
from actuarycanary.quality.model import Outcome

TREATIES = "reinsurance_treaties"
MOVEMENTS = "reinsurance_transactions"
RECOVERIES = "recoveries"
LEDGER = "ledger"

PROPORTIONAL = ("QUOTA_SHARE", "SURPLUS")
POSITIVE_TYPES = ("CEDED_CLAIM_PAID", "CEDED_PREMIUM", "RI_COMMISSION", "REINSTATEMENT_PREMIUM")
PREMIUM_MOVEMENTS = ("CEDED_PREMIUM", "REINSTATEMENT_PREMIUM")
SHARED_WITH_PREMIUMS = ("CEDED_PREMIUM", "RI_COMMISSION")  # DV-RTR-11
BALANCE_TOLERANCE = 0.01  # DV-LDG-06 and -07: within 0.01 of the currency's unit
_EPSILON = 1e-9  # room for the binary representation of amounts in cents
FISCAL_YEAR_START_MONTH = 1  # DV-LDG-07 until the mapping profile (CV12) says otherwise

# the other feeds a rule needs beside its own
NEEDS: dict[str, tuple[str, ...]] = {
    "DV-RTY-10": ("market",),
    "DV-RTR-05": (TREATIES,),
    "DV-RTR-06": (TREATIES, "claims"),
    "DV-RTR-07": ("claims",),
    "DV-RTR-08": ("claim_valuations",),
    "DV-RTR-09": ("claim_valuations",),
    "DV-RTR-11": ("premiums", "policies"),
    "DV-RCV-05": ("claim_valuations",),
    "DV-RCV-06": ("claim_valuations",),
    "DV-RCV-07": ("claim_valuations",),
    "DV-RCV-08": ("claim_valuations",),
}
# rules that cannot be evaluated yet, with the reason the quality report gives
NOT_BUILT: dict[str, str] = {
    "DV-LDG-09": "it needs the account-mapping profile (CV12), which is not built yet",
}


def _column(frame: pl.DataFrame, name: str, dtype: pl.DataType | None = None) -> pl.Expr:
    """The column, or an empty one when the feed does not carry it."""
    if name in frame.columns:
        return pl.col(name)
    return pl.lit(None, dtype=dtype or pl.Float64()).alias(name)


def _with(frame: pl.DataFrame, numbers: tuple[str, ...] = (), text: tuple[str, ...] = ()):
    """`frame` with the optional columns named, empty where the feed lacks them."""
    missing = [_column(frame, n) for n in numbers if n not in frame.columns]
    missing += [_column(frame, n, pl.String()) for n in text if n not in frame.columns]
    return frame.with_columns(missing) if missing else frame


def _grouped(
    rule: str, concept: str, checked: int, failed: int, message: str, rows: pl.DataFrame
) -> Outcome:
    """Outcome of a rule about groups (claims, months, entities): the count is of groups."""
    refs = references(rows) if rows.height else ()
    return Outcome(rule, concept, checked, failed, message if failed else "", refs)


# --- reinsurance treaties ----------------------------------------------------------------


def terms_of_the_type(ctx: Context) -> Outcome | None:  # DV-RTY-05
    frame = _frame(ctx, TREATIES, ("treaty_type",))
    if frame is None:
        return None
    frame = _with(frame, ("cession_share", "retention", "number_of_lines"))
    kind = pl.col("treaty_type")
    missing = (
        ((kind == "QUOTA_SHARE") & pl.col("cession_share").is_null())
        | (
            (kind == "SURPLUS")
            & (pl.col("retention").is_null() | pl.col("number_of_lines").is_null())
        )
        | (kind.is_in(["EXCESS_OF_LOSS", "STOP_LOSS"]) & pl.col("retention").is_null())
    )
    return _outcome("DV-RTY-05", TREATIES, frame.height, frame.filter(missing.fill_null(False)))


def shares_between_zero_and_one(ctx: Context) -> Outcome | None:  # DV-RTY-06
    frame = ctx.frames.get(TREATIES)
    names = ("cession_share", "placed_share", "ceding_commission")
    used = [n for n in names if frame is not None and n in frame.columns]
    if frame is None or not used:
        return None
    outside = pl.any_horizontal([(pl.col(n) < 0) | (pl.col(n) > 1) for n in used])
    return _outcome("DV-RTY-06", TREATIES, frame.height, frame.filter(outside.fill_null(False)))


def terms_not_negative(ctx: Context) -> Outcome | None:  # DV-RTY-07
    frame = ctx.frames.get(TREATIES)
    names = ("retention", "limit", "aggregate_deductible", "aggregate_limit", "reinstatements")
    used = [n for n in names if frame is not None and n in frame.columns]
    lines = frame is not None and "number_of_lines" in frame.columns
    if frame is None or not (used or lines):
        return None
    bad = [pl.col(n) < 0 for n in used] + ([pl.col("number_of_lines") <= 0] if lines else [])
    return _outcome(
        "DV-RTY-07", TREATIES, frame.height, frame.filter(pl.any_horizontal(bad).fill_null(False))
    )


def treaties_do_not_overlap(ctx: Context) -> Outcome | None:  # DV-RTY-09
    """Rows of two different treaties that overlap in time on the same line and entity: two
    proportional treaties of the same type, or two excess-of-loss layers on the same loss basis
    whose bands [retention, retention + limit) overlap."""
    columns = ("treaty_id", "treaty_type", "inception_date", "expiry_date")
    frame = _frame(ctx, TREATIES, columns)
    if frame is None:
        return None
    frame = _with(frame, ("retention", "limit"), ("line", "entity", "loss_basis"))
    keep = [*columns, "retention", "limit", "line", "entity", "loss_basis", SOURCE_ROW]
    left = frame.select(keep)
    pairs = left.join(left, on="treaty_type", suffix="_b").filter(
        (pl.col("treaty_id") != pl.col("treaty_id_b"))
        & pl.col("line").eq_missing(pl.col("line_b"))
        & pl.col("entity").eq_missing(pl.col("entity_b"))
        & (pl.col("inception_date") < pl.col("expiry_date_b"))
        & (pl.col("inception_date_b") < pl.col("expiry_date"))
    )
    top = pl.col("retention") + pl.col("limit").fill_null(float("inf"))
    top_b = pl.col("retention_b") + pl.col("limit_b").fill_null(float("inf"))
    layers = (
        (pl.col("treaty_type") == "EXCESS_OF_LOSS")
        & pl.col("loss_basis").eq_missing(pl.col("loss_basis_b"))
        & (pl.col("retention") < top_b)
        & (pl.col("retention_b") < top)
    )
    overlapping = pairs.filter(pl.col("treaty_type").is_in(PROPORTIONAL) | layers.fill_null(False))
    rows = frame.filter(pl.col(SOURCE_ROW).is_in(overlapping[SOURCE_ROW].unique().implode()))
    return _outcome("DV-RTY-09", TREATIES, frame.height, rows)


def index_series_in_market(ctx: Context) -> Outcome | None:  # DV-RTY-10
    frame = _frame(ctx, TREATIES, ("index_series",))
    market = _frame(ctx, "market", ("series_id", "kind"))
    if frame is None or market is None:
        return None
    known = market.filter(pl.col("kind") == "PRICE_INDEX")["series_id"].drop_nulls().unique()
    named = frame.filter(pl.col("index_series").is_not_null())
    return _outcome(
        "DV-RTY-10",
        TREATIES,
        named.height,
        named.filter(~pl.col("index_series").is_in(known.implode())),
    )


# --- reinsurance transactions --------------------------------------------------------------


def movement_within_the_treaty(ctx: Context) -> Outcome | None:  # DV-RTR-06
    """A claim movement whose claim no contract period of its treaty covers (by the date of
    loss, or by the policy start for a risks-attaching treaty), or a premium movement booked
    before the first inception date of its treaty. Movements whose treaty or claim is unknown
    are left to DV-RTR-05 and DV-RTR-07."""
    frame = _frame(ctx, MOVEMENTS, ("treaty_id", "booking_date", "type"))
    treaties = _frame(ctx, TREATIES, ("treaty_id", "inception_date", "expiry_date"))
    claims = _frame(ctx, "claims", ("claim_id", "occurrence_date"))
    if frame is None or treaties is None or claims is None:
        return None
    frame = _with(frame, text=("claim_id",))
    treaties = _with(treaties, text=("attachment_basis",))
    periods = treaties.select("treaty_id", "inception_date", "expiry_date", "attachment_basis")
    known = frame.filter(pl.col("treaty_id").is_in(periods["treaty_id"].unique().implode()))

    dates = claims.select("claim_id", "occurrence_date").unique(subset="claim_id")
    policies = ctx.frames.get("policies")
    if policies is not None and "policy_id" in claims.columns and "start_date" in policies.columns:
        starts = policies.select("policy_id", "start_date").unique(subset="policy_id")
        dates = (
            claims.select("claim_id", "occurrence_date", "policy_id")
            .unique(subset="claim_id")
            .join(starts, on="policy_id", how="left")
            .drop("policy_id")
        )
    else:
        dates = dates.with_columns(pl.lit(None, dtype=pl.Date()).alias("start_date"))
    on_claims = known.filter(pl.col("claim_id").is_not_null()).join(dates, on="claim_id")
    day = (
        pl.when(pl.col("attachment_basis") == "RISKS_ATTACHING")
        .then(pl.col("start_date").fill_null(pl.col("occurrence_date")))
        .otherwise(pl.col("occurrence_date"))
    )
    covered = (
        on_claims.join(periods, on="treaty_id")
        .with_columns(day.alias("_day"))
        .with_columns(
            (
                (pl.col("_day") >= pl.col("inception_date"))
                & (pl.col("_day") < pl.col("expiry_date"))
            ).alias("_covered")
        )
        .group_by(SOURCE_ROW)
        .agg(pl.col("_covered").any())
    )
    outside = covered.filter(~pl.col("_covered"))[SOURCE_ROW]

    first = periods.group_by("treaty_id").agg(pl.col("inception_date").min().alias("_first"))
    premiums = known.filter(pl.col("type").is_in(PREMIUM_MOVEMENTS)).join(first, on="treaty_id")
    early = premiums.filter(pl.col("booking_date") < pl.col("_first"))[SOURCE_ROW]

    failing = frame.filter(pl.col(SOURCE_ROW).is_in(pl.concat([outside, early]).implode()))
    return _outcome("DV-RTR-06", MOVEMENTS, on_claims.height + premiums.height, failing)


def _ceded_at_valuations(ctx: Context) -> pl.DataFrame | None:
    """Per valuation row: the ceded paid and the ceded case reserve accumulated from the claim
    movements booked up to its date, beside the fields of the valuation."""
    frame = _frame(ctx, MOVEMENTS, ("claim_id", "booking_date", "amount", "type"))
    valuations = _frame(ctx, "claim_valuations", ("claim_id", "valuation_date"))
    if frame is None or valuations is None:
        return None
    moves = frame.filter(pl.col("claim_id").is_not_null())
    paid = cumulative_at(valuations, moves.filter(pl.col("type") == "CEDED_CLAIM_PAID"), "_paid")
    held = cumulative_at(
        valuations, moves.filter(pl.col("type") == "CEDED_CASE_RESERVE"), "_reserve"
    )
    with_movements = moves["claim_id"].unique()
    return (
        valuations.filter(pl.col("claim_id").is_in(with_movements.implode()))
        .join(paid, on=["claim_id", "valuation_date"], how="left")
        .join(held, on=["claim_id", "valuation_date"], how="left")
    )


def ceded_within_gross_movements(ctx: Context) -> Outcome | None:  # DV-RTR-08
    rows = _ceded_at_valuations(ctx)
    if rows is None or not {"paid_to_date", "case_reserve"} <= set(rows.columns):
        return None
    above = (pl.col("_paid") > pl.col("paid_to_date") + AMOUNT_TOLERANCE) | (
        pl.col("_reserve") > pl.col("case_reserve") + AMOUNT_TOLERANCE
    )
    return _outcome("DV-RTR-08", MOVEMENTS, rows.height, rows.filter(above.fill_null(False)))


def movements_agree_with_valuations(ctx: Context) -> Outcome | None:  # DV-RTR-09
    rows = _ceded_at_valuations(ctx)
    pairs = [
        (own, field)
        for own, field in (("_paid", "ceded_paid_to_date"), ("_reserve", "ceded_reserve"))
        if rows is not None and field in rows.columns
    ]
    if rows is None or not pairs:
        return None
    differ = pl.any_horizontal(
        [(pl.col(own) - pl.col(field)).abs() > AMOUNT_TOLERANCE for own, field in pairs]
    )
    return _outcome("DV-RTR-09", MOVEMENTS, rows.height, rows.filter(differ.fill_null(False)))


def agrees_with_premiums(ctx: Context) -> Outcome | None:  # DV-RTR-11
    """Ceded premium and reinsurance commission per month, line and currency: this feed against
    the premiums feed, when premiums holds such rows. The line of a premium row is its policy's."""
    frame = _frame(ctx, MOVEMENTS, ("booking_date", "amount", "type", "currency"))
    premiums = _frame(ctx, "premiums", ("policy_id", "booking_date", "amount", "type", "currency"))
    policies = _frame(ctx, "policies", ("policy_id", "line"))
    if frame is None or premiums is None or policies is None:
        return None
    ceded = premiums.filter(pl.col("type").is_in(SHARED_WITH_PREMIUMS))
    if ceded.height == 0:
        return None
    keys = ["type", "_month", "line", "currency"]
    month = pl.col("booking_date").dt.month_end().alias("_month")
    lines = policies.select("policy_id", "line").unique(subset="policy_id")
    theirs = (
        ceded.join(lines, on="policy_id", how="left")
        .with_columns(month)
        .group_by(keys)
        .agg(pl.col("amount").sum().alias("_premiums"))
    )
    own = _with(frame, text=("line",)).filter(pl.col("type").is_in(SHARED_WITH_PREMIUMS))
    mine = (
        own.with_columns(month)
        .group_by(keys)
        .agg(pl.col("amount").sum().alias("_movements"), pl.col(SOURCE_ROW).min())
    )
    both = theirs.join(mine, on=keys, how="full", coalesce=True, nulls_equal=True)
    gap = pl.col("_premiums").fill_null(0.0) - pl.col("_movements").fill_null(0.0)
    differing = both.filter(gap.abs() > AMOUNT_TOLERANCE)
    rows = frame.filter(pl.col(SOURCE_ROW).is_in(differing[SOURCE_ROW].drop_nulls().implode()))
    message = (
        f"{differing.height} of {both.height} totals of ceded premium or commission per month, "
        "line and currency differ from the premiums feed"
    )
    return _grouped("DV-RTR-11", MOVEMENTS, both.height, differing.height, message, rows)


# --- recoveries ------------------------------------------------------------------------------


def booked_after_the_claim_was_reported(ctx: Context) -> Outcome | None:  # DV-RCV-06
    frame = _frame(ctx, RECOVERIES, ("claim_id", "booking_date"))
    claims = _frame(ctx, "claims", ("claim_id", "report_date"))
    valuations = _frame(ctx, "claim_valuations", ("claim_id", "valuation_date"))
    if frame is None or (claims is None and valuations is None):
        return None
    if claims is not None:
        first = claims.select("claim_id", pl.col("report_date").alias("_first"))
    else:
        assert valuations is not None
        first = valuations.group_by("claim_id").agg(pl.col("valuation_date").min().alias("_first"))
    dated = frame.join(first.unique(subset="claim_id"), on="claim_id").filter(
        pl.col("_first").is_not_null()
    )
    return _outcome(
        "DV-RCV-06",
        RECOVERIES,
        dated.height,
        dated.filter(pl.col("booking_date") < pl.col("_first")),
    )


def recovered_at_most_paid(ctx: Context) -> Outcome | None:  # DV-RCV-07
    """Claims whose recoveries booked up to the cut-off exceed their paid_to_date there."""
    frame = _frame(ctx, RECOVERIES, ("claim_id", "booking_date", "amount"))
    valuations = _frame(ctx, "claim_valuations", ("claim_id", "valuation_date", "paid_to_date"))
    if frame is None or valuations is None:
        return None
    upto = (
        valuations
        if ctx.cut_off is None
        else valuations.filter(pl.col("valuation_date") <= ctx.cut_off)
    )
    paid = (
        upto.sort("valuation_date", SOURCE_ROW)
        .group_by("claim_id")
        .agg(pl.col("paid_to_date").last().alias("_paid"))
    )
    booked = frame if ctx.cut_off is None else frame.filter(pl.col("booking_date") <= ctx.cut_off)
    recovered = booked.group_by("claim_id").agg(
        pl.col("amount").sum().alias("_recovered"), pl.col(SOURCE_ROW).min().alias("_row")
    )
    both = recovered.join(paid, on="claim_id").filter(pl.col("_paid").is_not_null())
    above = both.filter(pl.col("_recovered") > pl.col("_paid") + AMOUNT_TOLERANCE)
    rows = frame.filter(pl.col(SOURCE_ROW).is_in(above["_row"].implode()))
    message = (
        f"{above.height} of {both.height} claims have recovered more than was paid at the "
        "cut-off; their paid net of recoveries is negative"
    )
    return _grouped("DV-RCV-07", RECOVERIES, both.height, above.height, message, rows)


def agrees_with_to_date_fields(ctx: Context) -> Outcome | None:  # DV-RCV-08
    frame = _frame(ctx, RECOVERIES, ("claim_id", "booking_date", "amount", "type"))
    valuations = _frame(ctx, "claim_valuations", ("claim_id", "valuation_date"))
    if frame is None or valuations is None:
        return None
    fields = to_date_fields(valuations)
    if not fields:
        return None
    differences = recovery_differences(frame, valuations)
    checked = sum(int(valuations[name].is_not_null().sum()) for name in fields.values())
    if differences.height == 0:
        return Outcome("DV-RCV-08", RECOVERIES, checked, 0)
    worst = differences.sort(pl.col("difference").abs(), descending=True).head(3)
    shown = "; ".join(
        f"claim {r['claim_id']} {r['type']} at {r['valuation_date']}: booked {r['booked']:.2f}, "
        f"to-date field {r['to_date']:.2f}"
        for r in worst.iter_rows(named=True)
    )
    message = (
        f"{differences.height} valuations where the recoveries booked for a claim and type "
        f"differ from the to-date field; the transactions are used (largest: {shown})"
    )
    rows = differences.select(SOURCE_COLUMNS) if SOURCE_ROW in differences.columns else differences
    return Outcome("DV-RCV-08", RECOVERIES, checked, differences.height, message, references(rows))


# --- ledger ----------------------------------------------------------------------------------


def closing_is_opening_plus_movement(ctx: Context) -> Outcome | None:  # DV-LDG-06
    columns = ("opening_balance", "debit", "credit", "closing_balance")
    gap = pl.col("closing_balance") - (
        pl.col("opening_balance") + pl.col("debit") - pl.col("credit")
    )
    return _rows(
        "DV-LDG-06",
        LEDGER,
        columns,
        gap.abs() > BALANCE_TOLERANCE + _EPSILON,
        pl.all_horizontal(pl.col(*columns).is_not_null()),
    )(ctx)


def opening_is_previous_closing(ctx: Context) -> Outcome | None:  # DV-LDG-07
    """Against the row before it of the same entity, account and currency; when months are
    missing between the two rows the break shows the gap. An opening balance of zero in the
    first month of the fiscal year is the reset of a year-to-date income account and no break
    (record 0384)."""
    frame = _frame(ctx, LEDGER, ("entity", "account", "period", "opening_balance"))
    if frame is None or "closing_balance" not in frame.columns:
        return None
    frame = _with(frame, text=("currency",))
    over = ["entity", "account", "currency"]
    ordered = frame.sort(*over, "period").with_columns(
        pl.col("closing_balance").shift(1).over(over).alias("_previous")
    )
    reset = (pl.col("period").dt.month() == FISCAL_YEAR_START_MONTH) & (
        pl.col("opening_balance").abs() <= BALANCE_TOLERANCE
    )
    chained = ordered.filter(
        pl.col("_previous").is_not_null() & pl.col("opening_balance").is_not_null() & ~reset
    )
    broken = (pl.col("opening_balance") - pl.col("_previous")).abs() > BALANCE_TOLERANCE + _EPSILON
    return _outcome("DV-LDG-07", LEDGER, chained.height, chained.filter(broken))


def books_balance(ctx: Context) -> Outcome | None:  # DV-LDG-08
    frame = _frame(ctx, LEDGER, ("entity", "period", "closing_balance"))
    if frame is None:
        return None
    frame = _with(frame, text=("currency",))
    keys = ["entity", "period", "currency"]
    sums = frame.group_by(keys).agg(
        pl.col("closing_balance").sum().alias("_sum"), pl.col(SOURCE_ROW).min().alias("_row")
    )
    off = sums.filter(pl.col("_sum").abs() > AMOUNT_TOLERANCE).sort("period", "entity")
    rows = frame.filter(pl.col(SOURCE_ROW).is_in(off["_row"].implode()))
    shown = "; ".join(
        f"{r['entity']} {r['period']}: {r['_sum']:,.2f}" for r in off.head(3).iter_rows(named=True)
    )
    message = (
        f"{off.height} of {sums.height} entity-months do not sum to zero ({shown}); usually a "
        "partial extract, which is fine for reconciliation"
    )
    return _grouped("DV-LDG-08", LEDGER, sums.height, off.height, message, rows)


def every_month_has_a_row(ctx: Context) -> Outcome | None:  # DV-LDG-10
    frame = _frame(ctx, LEDGER, ("entity", "period"))
    if frame is None:
        return None
    month = (pl.col("period").dt.year() * 12 + pl.col("period").dt.month() - 1).alias("_month")
    present = (
        frame.with_columns(month)
        .group_by("entity")
        .agg(
            pl.col("_month").min().alias("_low"),
            pl.col("_month").max().alias("_high"),
            pl.col("_month").unique().alias("_months"),
            pl.col(SOURCE_ROW).min().alias("_row"),
        )
    )
    expected = 0
    missing: list[str] = []
    rows: list[int] = []
    for entity in present.sort("entity").iter_rows(named=True):
        have = set(entity["_months"])
        wanted = range(entity["_low"], entity["_high"] + 1)
        expected += len(wanted)
        gaps = [m for m in wanted if m not in have]
        if gaps:
            rows.append(entity["_row"])
            missing += [f"{entity['entity']} {m // 12}-{m % 12 + 1:02d}" for m in gaps]
    message = (
        f"{len(missing)} entity-months without a row ({'; '.join(missing[:5])}); reconciliation "
        "of those months is not available"
    )
    listed = frame.filter(pl.col(SOURCE_ROW).is_in(rows))
    return _grouped("DV-LDG-10", LEDGER, expected, len(missing), message, listed)


def not_evaluated_yet(_: Context) -> Outcome | None:  # rules of NOT_BUILT
    return None


positive = pl.col("amount") > 0

FEED_CHECKS: dict[str, Check] = {
    "DV-RTY-04": iso_currency("DV-RTY-04", TREATIES),
    "DV-RTY-05": terms_of_the_type,
    "DV-RTY-06": shares_between_zero_and_one,
    "DV-RTY-07": terms_not_negative,
    "DV-RTY-09": treaties_do_not_overlap,
    "DV-RTY-10": index_series_in_market,
    "DV-RTR-05": in_other("DV-RTR-05", MOVEMENTS, "treaty_id", TREATIES),
    "DV-RTR-06": movement_within_the_treaty,
    "DV-RTR-07": in_other("DV-RTR-07", MOVEMENTS, "claim_id", "claims"),
    "DV-RTR-08": ceded_within_gross_movements,
    "DV-RTR-09": movements_agree_with_valuations,
    "DV-RTR-10": _rows(
        "DV-RTR-10", MOVEMENTS, ("amount", "type"), ~positive, pl.col("type").is_in(POSITIVE_TYPES)
    ),
    "DV-RTR-11": agrees_with_premiums,
    "DV-RCV-05": in_other("DV-RCV-05", RECOVERIES, "claim_id", "claim_valuations"),
    "DV-RCV-06": booked_after_the_claim_was_reported,
    "DV-RCV-07": recovered_at_most_paid,
    "DV-RCV-08": agrees_with_to_date_fields,
    "DV-RCV-09": _rows("DV-RCV-09", RECOVERIES, ("amount",), ~positive),
    "DV-LDG-03": iso_currency("DV-LDG-03", LEDGER),
    "DV-LDG-06": closing_is_opening_plus_movement,
    "DV-LDG-07": opening_is_previous_closing,
    "DV-LDG-08": books_balance,
    "DV-LDG-09": not_evaluated_yet,
    "DV-LDG-10": every_month_has_a_row,
}
