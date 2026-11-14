"""FN01 and FN02 (CV12, record 0422): the gap between the platform's figure and the books, and
the share of the books the account-mapping profile cannot see.

Both read the account-mapping profile and the materiality settings of the run from
`inputs.cache[RUN_KEY]`; a call without them (a measure asked on its own) proposes a profile from
the ledger and uses the defaults of CV12.
"""

from dataclasses import dataclass

import polars as pl

from actuarycanary.ledger.balances import mapped_amounts
from actuarycanary.ledger.classes import RECONCILED_CLASSES
from actuarycanary.ledger.profile import ProfileInUse, assign
from actuarycanary.ledger.resolve import profile_in_use
from actuarycanary.ledger.settings import LedgerSettings
from actuarycanary.measures.ledger_platform import LINKS, Side, platform_side
from actuarycanary.measures.model import VALUE, Computed, MeasureInputs, MeasureRequest, Missing
from actuarycanary.spec.models import MeasureSpec

LEDGER = "ledger"
RUN_KEY = "ledger_run"
SIDES_KEY = "ledger_platform_sides"
CENT = 2
GRAIN = "the reconciliation is by entity, account class and month; segment and line are not built"

GAP_COLUMNS = (
    "entity",
    "account_class",
    "period",
    "platform_amount",
    "ledger_amount",
    "gap",
    "share",
    "material",
    "note",
)
NOT_RECONCILED_COLUMNS = ("account_class", "reason")


@dataclass(frozen=True)
class LedgerRun:
    """What a run decided about the ledger: the profile in use and the materiality."""

    use: ProfileInUse
    settings: LedgerSettings


def ledger_run(inputs: MeasureInputs) -> LedgerRun:
    cached = inputs.cache.get(RUN_KEY)
    if isinstance(cached, LedgerRun):
        return cached
    use = profile_in_use(inputs.feeds[LEDGER], None, inputs.fiscal_year_start_month)
    return LedgerRun(use, LedgerSettings())


def reporting_ledger(inputs: MeasureInputs) -> tuple[pl.DataFrame, list[str]]:
    """The ledger rows in the reporting currency (an empty currency means it, DV-LDG-03); the
    rows of other currencies are left out, a ledger with several currencies is not built."""
    ledger = inputs.feeds[LEDGER]
    if "currency" not in ledger.columns:
        return ledger, []
    same = pl.col("currency").is_null() | (pl.col("currency") == inputs.reporting_currency)
    left = ledger.filter(~same).height
    notes = (
        [f"{left} ledger rows in another currency than {inputs.reporting_currency} left out"]
        if left
        else []
    )
    return ledger.filter(same), notes


def ledger_amounts(
    ledger: pl.DataFrame, run: LedgerRun, fiscal_year_start_month: int
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """The mapped ledger amount per entity, class and month (null where a movement cannot be
    told), and the (entity, month) pairs the ledger has rows for."""
    pairs = ledger.select("entity", "account").unique().iter_rows()
    assignment = assign(run.use.profile, pairs)
    mapped = mapped_amounts(ledger, assignment, fiscal_year_start_month)
    amounts = (
        mapped.group_by("entity", "account_class", "period")
        .agg(
            (pl.col("signed").sum().round(CENT) + 0.0).alias("ledger_amount"),  # no negative zero
            pl.col("signed").is_null().any().alias("_unknown"),
        )
        .with_columns(
            pl.when(pl.col("_unknown"))
            .then(None)
            .otherwise(pl.col("ledger_amount"))
            .alias("ledger_amount")
        )
        .drop("_unknown")
    )
    months = ledger.select("entity", "period").unique()
    return amounts, months


def gap_table(
    amounts: pl.DataFrame,
    months: pl.DataFrame,
    sides: dict[str, Side],
    settings: LedgerSettings,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """FN01: the gap rows and the classes that are not reconciled with the reason.

    A class is reconciled for an entity when the profile maps an account of the entity to it and
    its platform side exists; its months are those the ledger has rows for (a missing month is
    not computed, DV-LDG-10). A month outside the range of the platform's feed is not computed."""
    present = amounts.select("entity", "account_class").unique()
    parts: list[pl.DataFrame] = []
    not_reconciled: list[tuple[str, str]] = []
    for account_class in sorted(present["account_class"].unique().to_list()):
        link_side = sides.get(account_class)
        if account_class not in RECONCILED_CLASSES:
            not_reconciled.append(
                (account_class, "mapped, deliberately not reconciled: no platform measure")
            )
            continue
        if link_side is None or link_side.frame is None:
            reason = "no figure" if link_side is None else link_side.reason
            not_reconciled.append((account_class, reason))
            continue
        entities = present.filter(pl.col("account_class") == account_class).select("entity")
        grid = months.join(entities, on="entity").with_columns(
            pl.lit(account_class).alias("account_class")
        )
        ledger_side = amounts.filter(pl.col("account_class") == account_class).with_columns(
            pl.lit(True).alias("_row")
        )
        rows = grid.join(ledger_side, on=["entity", "account_class", "period"], how="left")
        # the ledger has rows for the month and no account of the class moved: zero; a month
        # whose movement could not be told stays null
        rows = rows.with_columns(
            pl.when(pl.col("_row").is_null())
            .then(0.0)
            .otherwise(pl.col("ledger_amount"))
            .alias("ledger_amount")
        ).drop("_row")
        platform = link_side.frame.select(
            "entity", "period", pl.col("amount").round(CENT).alias("platform_amount")
        )
        rows = rows.join(platform, on=["entity", "period"], how="left")
        parts.append(rows)
    columns = {
        "entity": pl.String,
        "account_class": pl.String,
        "period": pl.Date,
        "platform_amount": pl.Float64,
        "ledger_amount": pl.Float64,
    }
    both = pl.concat(parts) if parts else pl.DataFrame(schema=columns)
    gap = (pl.col("platform_amount") - pl.col("ledger_amount")).round(CENT)
    threshold = pl.max_horizontal(
        pl.lit(settings.materiality_amount),
        settings.materiality_ratio * pl.col("ledger_amount").abs(),
    )
    table = both.with_columns(gap.alias("gap")).with_columns(
        pl.when(pl.col("ledger_amount") != 0)
        .then(pl.col("gap") / pl.col("ledger_amount").abs())
        .alias("share"),
        (pl.col("gap").abs() > threshold).fill_null(False).alias("material"),
        pl.when(pl.col("ledger_amount").is_null())
        .then(pl.lit("the movement of a year-to-date account cannot be told: not computed"))
        .when(pl.col("platform_amount").is_null())
        .then(pl.lit("outside the period of the platform's feed: not computed"))
        .when((pl.col("ledger_amount") == 0) & (pl.col("gap") != 0))
        .then(pl.lit("ledger amount is zero: the share is not computed"))
        .otherwise(pl.lit(""))
        .alias("note"),
    )
    reasons = pl.DataFrame(
        not_reconciled, schema=dict.fromkeys(NOT_RECONCILED_COLUMNS, pl.String), orient="row"
    )
    return table.select(*GAP_COLUMNS).sort("entity", "account_class", "period"), reasons


def platform_sides(inputs: MeasureInputs, classes: list[str]) -> dict[str, Side]:
    cache: dict[str, Side] = inputs.cache.setdefault(SIDES_KEY, {})
    for account_class in classes:
        if account_class in LINKS and account_class not in cache:
            cache[account_class] = platform_side(inputs, account_class)
    return {c: cache[c] for c in classes if c in cache}


def reconciliation_gap(
    spec: MeasureSpec, inputs: MeasureInputs, request: MeasureRequest
) -> Computed | Missing:
    """FN01: the platform's figure minus the mapped ledger amount per entity, class and month."""
    run = ledger_run(inputs)
    ledger, notes = reporting_ledger(inputs)
    amounts, months = ledger_amounts(ledger, run, inputs.fiscal_year_start_month)
    if amounts.height == 0:
        return Missing("the account-mapping profile maps no account of the ledger to a class")
    classes = sorted(amounts["account_class"].unique().to_list())
    sides = platform_sides(inputs, classes)
    table, reasons = gap_table(amounts, months, sides, run.settings)
    side_notes = [n for c in classes if c in sides for n in sides[c].notes]
    state = "confirmed" if run.use.profile.confirmed else "proposed, not confirmed"
    notes += [f"account-mapping profile {run.use.profile.fingerprint}: {state}", *side_notes]
    for row in reasons.iter_rows(named=True):
        notes.append(f"{row['account_class']} not reconciled: {row['reason']}")
    frame = table.with_columns(
        pl.col("gap").alias(VALUE),
        pl.col("period").dt.strftime("%Y-%m").alias("calendar_period"),
    )
    return Computed(frame, tuple(dict.fromkeys(notes)), (), {"not_reconciled": reasons})


def share_frame(inputs: MeasureInputs) -> tuple[pl.DataFrame, list[str]]:
    """FN02 per entity and month: `numerator`, `denominator`, `value` (null when all balances
    are zero) and `note`."""
    run = ledger_run(inputs)
    ledger, notes = reporting_ledger(inputs)
    assignment = assign(run.use.profile, ledger.select("entity", "account").unique().iter_rows())
    left = {*assignment.unmapped, *((t.entity, t.account) for t in assignment.ties)}
    key = pl.concat_str("entity", pl.lit("\x00"), "account")
    unmapped = key.is_in([f"{e}\x00{a}" for e, a in left])
    absolute = pl.col("closing_balance").abs()
    frame = (
        ledger.group_by("entity", "period")
        .agg(
            absolute.filter(unmapped).sum().alias("numerator"),
            absolute.sum().alias("denominator"),
        )
        .with_columns(
            pl.when(pl.col("denominator") > 0)
            .then(pl.col("numerator") / pl.col("denominator"))
            .alias(VALUE),
            pl.when(pl.col("denominator") > 0)
            .then(pl.lit(""))
            .otherwise(pl.lit("all balances are zero: not computed"))
            .alias("note"),
        )
        .sort("entity", "period")
    )
    return frame, notes


def unmapped_share(
    spec: MeasureSpec, inputs: MeasureInputs, request: MeasureRequest
) -> Computed | Missing:
    """FN02: absolute closing balances of the accounts the profile does not map over all absolute
    closing balances, per entity and month."""
    frame, notes = share_frame(inputs)
    frame = frame.with_columns(pl.col("period").dt.strftime("%Y-%m").alias("calendar_period"))
    return Computed(frame, tuple(notes), ())
