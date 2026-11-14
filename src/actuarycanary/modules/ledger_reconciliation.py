"""M10 Ledger reconciliation: the tables of the module beside its measures (FN01, FN02): the
reconciliation per entity, class and month with the likely causes of each material gap, the
accounts the profile does not map, and the profile in use (records 0421 to 0424)."""

from dataclasses import dataclass
from datetime import date

import polars as pl

from actuarycanary.ledger import causes as causes_module
from actuarycanary.ledger.causes import Cause
from actuarycanary.ledger.profile import AccountProfile, Assignment, assign
from actuarycanary.ledger.settings import LedgerSettings
from actuarycanary.measures.ledger_measures import (
    gap_table,
    ledger_amounts,
    ledger_run,
    platform_sides,
    reporting_ledger,
    share_frame,
)
from actuarycanary.measures.ledger_platform import FOREIGN, Side
from actuarycanary.measures.model import MeasureInputs

NO_CAUSE = "no cause suggested"
PROPOSED = "proposed, not confirmed"
RECONCILIATION_COLUMNS = (
    "entity",
    "account_class",
    "period",
    "platform_amount",
    "ledger_amount",
    "gap",
    "share",
    "material",
    "note",
    "suggested_causes",
    "cause_evidence",
    "ledger_mapping",
)
UNMAPPED_COLUMNS = (
    "entity",
    "account",
    "account_name",
    "reason",
    "latest_period",
    "latest_balance",
    "largest_balance",
    "months_with_balance",
)
RULE_COLUMNS = ("entity", "pattern", "account_class", "sign", "balance_kind", "line")


def mapping_label(profile: AccountProfile) -> str:
    """The state of the profile as every ledger figure says it (CV12)."""
    if profile.confirmed_on is None:
        return PROPOSED
    return f"confirmed on {profile.confirmed_on.isoformat()}"


@dataclass(frozen=True)
class LedgerTables:
    reconciliation: pl.DataFrame  # RECONCILIATION_COLUMNS
    not_reconciled: pl.DataFrame  # account_class, reason
    unmapped: pl.DataFrame  # UNMAPPED_COLUMNS
    share: pl.DataFrame  # FN02: entity, period, numerator, denominator, value, note
    rules: pl.DataFrame  # RULE_COLUMNS
    fingerprint: str
    sha256: str
    mapping: str  # mapping_label of the profile
    settings: LedgerSettings
    notes: tuple[str, ...]

    @property
    def material(self) -> pl.DataFrame:
        return self.reconciliation.filter(pl.col("material"))


def _unmapped_balances(
    ledger: pl.DataFrame, assignment: Assignment
) -> tuple[pl.DataFrame, dict[tuple[str, date], tuple[float, list[str]]]]:
    """The unmapped accounts with a balance, and per entity and month the absolute balance they
    hold together with their codes."""
    ties = {(t.entity, t.account): t.patterns for t in assignment.ties}
    left = {*assignment.unmapped, *ties}
    names = pl.col("account_name") if "account_name" in ledger.columns else pl.lit(None, pl.String)
    rows = ledger.with_columns(names.alias("_name"))
    rows = rows.filter(
        pl.concat_str("entity", pl.lit("\x00"), "account").is_in([f"{e}\x00{a}" for e, a in left])
    )
    live = rows.filter(pl.col("closing_balance").abs() > 0)
    accounts = (
        live.sort("period")
        .group_by("entity", "account", maintain_order=True)
        .agg(
            pl.col("_name").drop_nulls().first().alias("account_name"),
            pl.col("period").last().alias("latest_period"),
            pl.col("closing_balance").last().alias("latest_balance"),
            pl.col("closing_balance").abs().max().alias("largest_balance"),
            pl.len().cast(pl.Int64).alias("months_with_balance"),
        )
        .with_columns(
            pl.struct("entity", "account")
            .map_elements(
                lambda r: (
                    "two rules of the same precedence claim it: "
                    + ", ".join(ties[(r["entity"], r["account"])])
                    if (r["entity"], r["account"]) in ties
                    else "no rule of the profile matches it"
                ),
                return_dtype=pl.String,
            )
            .alias("reason")
        )
        .select(*UNMAPPED_COLUMNS)
        .sort("entity", "account")
    )
    held: dict[tuple[str, date], tuple[float, list[str]]] = {}
    for row in (
        live.group_by("entity", "period")
        .agg(
            pl.col("closing_balance").abs().sum().alias("_held"), pl.col("account").unique().sort()
        )
        .iter_rows(named=True)
    ):
        held[(row["entity"], row["period"])] = (row["_held"], row["account"])
    return accounts, held


def _causes(
    table: pl.DataFrame,
    sides: dict[str, Side],
    held: dict[tuple[str, date], tuple[float, list[str]]],
) -> pl.DataFrame:
    """Add `suggested_causes` and `cause_evidence` to the material rows of the gap table."""
    foreign: dict[tuple[str, str, date], float] = {}
    for account_class, side in sides.items():
        if side.frame is not None and FOREIGN in side.frame.columns:
            for r in side.frame.iter_rows(named=True):
                foreign[(r["entity"], account_class, r["period"])] = r[FOREIGN]
    gaps: dict[tuple[str, str], dict[date, float]] = {}
    loadings: dict[tuple[str, str], dict[date, float]] = {}
    for r in table.iter_rows(named=True):
        if r["gap"] is None:
            continue
        key = (r["entity"], r["account_class"])
        gaps.setdefault(key, {})[r["period"]] = r["gap"]
        ledger, platform = r["ledger_amount"], r["platform_amount"]
        if r["material"] and ledger and platform and platform > 0 and ledger > platform:
            loadings.setdefault(key, {})[r["period"]] = (ledger - platform) / platform
    suggested: list[str] = []
    evidence: list[str] = []
    for r in table.iter_rows(named=True):
        if not r["material"]:
            suggested.append("")
            evidence.append("")
            continue
        key = (r["entity"], r["account_class"])
        found: list[Cause | None] = [
            causes_module.cut_off_timing(r["period"], gaps.get(key, {})),
            causes_module.currency(r["gap"], foreign.get((*key, r["period"]))),
            causes_module.ibnr_in_outstanding(
                r["account_class"], r["period"], loadings.get(key, {})
            ),
        ]
        balance, accounts = held.get((r["entity"], r["period"]), (0.0, []))
        found.append(causes_module.unmapped_account(r["gap"], balance, accounts))
        real = [c for c in found if c is not None]
        suggested.append("; ".join(c.code for c in real) if real else NO_CAUSE)
        evidence.append(" | ".join(c.evidence for c in real))
    return table.with_columns(
        pl.Series("suggested_causes", suggested, dtype=pl.String),
        pl.Series("cause_evidence", evidence, dtype=pl.String),
    )


def ledger_tables(inputs: MeasureInputs) -> LedgerTables:
    """The tables of M10 for the run: computed from the cached platform sides, so asking after
    the measures cost nothing more."""
    run = ledger_run(inputs)
    ledger, notes = reporting_ledger(inputs)
    amounts, months = ledger_amounts(ledger, run, inputs.fiscal_year_start_month)
    classes = sorted(amounts["account_class"].unique().to_list()) if amounts.height else []
    sides = platform_sides(inputs, classes)
    table, reasons = gap_table(amounts, months, sides, run.settings)
    assignment = assign(run.use.profile, ledger.select("entity", "account").unique().iter_rows())
    unmapped, held = _unmapped_balances(ledger, assignment)
    label = mapping_label(run.use.profile)
    reconciliation = _causes(table, sides, held).with_columns(pl.lit(label).alias("ledger_mapping"))
    share, _ = share_frame(inputs)
    rules = pl.DataFrame(
        [r.model_dump() | {"entity": r.entity} for r in run.use.profile.rules],
        schema={
            "entity": pl.String,
            "pattern": pl.String,
            "account_class": pl.String,
            "sign": pl.Int64,
            "balance_kind": pl.String,
            "line": pl.String,
        },
    )
    side_notes = [n for c in classes if c in sides for n in sides[c].notes]
    return LedgerTables(
        reconciliation.select(*RECONCILIATION_COLUMNS),
        reasons,
        unmapped,
        share,
        rules,
        run.use.profile.fingerprint,
        run.use.sha256,
        label,
        run.settings,
        tuple(dict.fromkeys([*notes, *side_notes])),
    )
