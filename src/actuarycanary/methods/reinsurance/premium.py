"""MT21 premium side: what a programme cedes of the gross premium, and the premium bases of the
non-proportional sections (decision 0403).

Proportional sections cede their share of the premium in the same inuring order as the claims:
facultative and surplus by the policy's share, quota share on what they leave (MT21, CV09).
Commission is `ceding_commission` times the ceded premium. A non-proportional section's
deposit premium (100 per cent) is `premium_rate` times its GNPI, the written premium of its
scope net of the inuring proportional cessions; its ceded premium is the placed share of that.
A stop loss needs the earned premium of its scope net of the same cessions.

Scope of premium (CV09): the policies of the section's entity, segment and line; written
premium by booking date in the period (LOSSES_OCCURRING; the generator cedes premium by its
booking date) or by the policy's start date (RISKS_ATTACHING); earned premium pro rata by days of
the policy term falling in the period.
"""

from dataclasses import dataclass
from datetime import date

import numpy as np
import polars as pl

from actuarycanary.methods.reinsurance.index import FxLookup, PriceIndex
from actuarycanary.methods.reinsurance.terms import (
    FACULTATIVE,
    QUOTA_SHARE,
    RISKS_ATTACHING,
    STAGES,
    STOP_LOSS,
    SURPLUS,
    Section,
)

PROPORTIONAL_STAGES = ("FACULTATIVE", "SURPLUS", "QUOTA_SHARE")


@dataclass(frozen=True)
class PremiumApplication:
    by_section: pl.DataFrame  # one row per section, see `apply_premium`

    def earned_premium(self) -> dict[tuple[str, date], float]:
        """Retained earned premium of each stop-loss section (the input of its layer)."""
        rows = self.by_section.filter(pl.col("treaty_type") == STOP_LOSS)
        return {
            (r["treaty_id"], r["inception_date"]): r["retained_earned"]
            for r in rows.iter_rows(named=True)
            if r["retained_earned"] is not None
        }

    def deposit_premium(self) -> dict[tuple[str, date], float]:
        """100 per cent deposit premium of each non-proportional section with a premium rate."""
        rows = self.by_section.filter(pl.col("deposit_premium").is_not_null())
        return {
            (r["treaty_id"], r["inception_date"]): r["deposit_premium"]
            for r in rows.iter_rows(named=True)
        }


def _scope(frame: pl.DataFrame, section: Section) -> np.ndarray:
    expr = pl.lit(True)
    if section.lines is not None:
        expr &= pl.col("line").is_in(sorted(section.lines)).fill_null(False)
    if section.segment is not None:
        expr &= (pl.col("segment") == section.segment).fill_null(False)
    if section.entity is not None:
        expr &= (pl.col("entity") == section.entity).fill_null(False)
    return frame.select(expr.alias("a"))["a"].to_numpy()


def _days(frame: pl.DataFrame, column: str) -> np.ndarray:
    return frame[column].cast(pl.Date).to_numpy().astype("datetime64[D]")


def _earned_share(frame: pl.DataFrame, start: date, end: date) -> np.ndarray:
    """Share of each written amount earned in [start, end): days of the policy term in the
    period over days of the term (pro rata, CV04)."""
    a, b = _days(frame, "start_date"), _days(frame, "end_date")
    lo = np.maximum(a, np.datetime64(start, "D"))
    hi = np.minimum(b, np.datetime64(end, "D"))
    term = (b - a).astype(np.int64)
    inside = np.maximum((hi - lo).astype(np.int64), 0)
    ok = ~(np.isnat(a) | np.isnat(b)) & (term > 0)
    return np.where(ok, inside / np.where(term > 0, term, 1), 0.0)


def _surplus_share(
    section: Section, frame: pl.DataFrame, price_index: dict[str, PriceIndex], fx: FxLookup | None
) -> np.ndarray:
    assert section.retention is not None and section.number_of_lines is not None
    line = np.full(frame.height, float(section.retention))
    series = price_index.get(section.index_series or "")
    start = _days(frame, "start_date")
    if series is not None:
        known = ~np.isnat(start)
        line[known] = line[known] * series.at(start[known]) / series.at_date(section.inception)
    insured = frame["sum_insured"].cast(pl.Float64).to_numpy().copy()
    currency = frame["currency"].to_list()
    starts = frame["start_date"].to_list()
    for i, (code, day) in enumerate(zip(currency, starts, strict=True)):
        if code is not None and code != section.currency:
            rate = None if fx is None or day is None else fx(code, section.currency, day)
            insured[i] = np.nan if rate is None else insured[i] * rate
    usable = np.isfinite(insured) & (insured > 0)
    share = np.zeros(frame.height)
    capacity = section.number_of_lines * line
    share[usable] = np.clip(insured[usable] - line[usable], 0.0, capacity[usable]) / insured[usable]
    return share


def apply_premium(
    sections: list[Section],
    written: pl.DataFrame,
    *,
    price_index: dict[str, PriceIndex] | None = None,
    fx: FxLookup | None = None,
    facultative_shares: dict[tuple[str, str], float] | None = None,
) -> PremiumApplication:
    """Premium of each section.

    `written` holds the gross written premium transactions (PR01 types) with the policy's
    attributes: policy_id, booking_date, amount, line, segment, entity, start_date, end_date,
    sum_insured, currency. Returns per section: gross written and gross earned premium in
    scope, the ceded premium and commission (proportional), the retained written premium
    (GNPI) and retained earned premium, the deposit premium at 100 per cent and the ceded
    premium of a non-proportional section.
    """
    price_index = price_index or {}
    shares = facultative_shares or {}
    for name, dtype in (
        ("segment", pl.String),
        ("entity", pl.String),
        ("currency", pl.String),
        ("sum_insured", pl.Float64),
        ("end_date", pl.Date),
    ):
        if name not in written.columns:
            written = written.with_columns(pl.lit(None, dtype=dtype).alias(name))
    amount = written["amount"].cast(pl.Float64).to_numpy()
    retained = amount.copy()  # premium left after each proportional stage, original currency
    rates: dict[str, np.ndarray] = {}

    def rate_into(target: str) -> np.ndarray:
        """Rate of each row into `target` at its booking date (CV01 flows); 0 when unknown."""
        if target not in rates:
            out = np.ones(written.height)
            cache: dict[tuple[object, object], float] = {}
            for i, (code, day) in enumerate(
                zip(written["currency"].to_list(), written["booking_date"].to_list(), strict=True)
            ):
                if code is None or code == target:
                    continue
                if (code, day) not in cache:
                    rate = None if fx is None or day is None else fx(code, target, day)
                    cache[(code, day)] = 0.0 if rate is None else float(rate)
                out[i] = cache[(code, day)]
            rates[target] = out
        return rates[target]

    rows: list[dict[str, object]] = []
    for stage in STAGES:
        stage_cession = np.zeros(written.height)
        for section in (s for s in sections if s.stage == stage):
            scope = _scope(written, section)
            day = "start_date" if section.attachment_basis == RISKS_ATTACHING else "booking_date"
            in_period = (
                ((written[day] >= section.inception) & (written[day] < section.expiry))
                .fill_null(False)
                .to_numpy()
            )
            written_mask = scope & in_period
            earned_share = np.where(
                scope, _earned_share(written, section.inception, section.expiry), 0.0
            )
            rate = rate_into(section.currency)
            row: dict[str, object] = {
                "treaty_id": section.treaty_id,
                "inception_date": section.inception,
                "treaty_type": section.treaty_type,
                "currency": section.currency,
                "gross_written": float((amount * rate)[written_mask].sum()),
                "gross_earned": float((amount * rate * earned_share).sum()),
                "retained_written": float((retained * rate)[written_mask].sum()),
                "retained_earned": float((retained * rate * earned_share).sum()),
                "ceded_premium": None,
                "commission": None,
                "deposit_premium": None,
            }
            if stage in PROPORTIONAL_STAGES:
                if section.treaty_type == QUOTA_SHARE:
                    share = np.full(written.height, float(section.cession_share or 0.0))
                elif section.treaty_type == SURPLUS:
                    share = _surplus_share(section, written, price_index, fx)
                else:
                    assert section.treaty_type == FACULTATIVE
                    policy = written["policy_id"].to_list()
                    share = np.array([shares.get((section.treaty_id, str(p)), 0.0) for p in policy])
                ceded = np.where(written_mask, share * section.placed_share * retained, 0.0)
                stage_cession += ceded
                row["ceded_premium"] = float((ceded * rate).sum())
                row["commission"] = float((ceded * rate).sum()) * float(
                    section.ceding_commission or 0.0
                )
            elif section.premium_rate is not None:
                deposit = section.premium_rate * float((retained * rate)[written_mask].sum())
                row["deposit_premium"] = deposit
                row["ceded_premium"] = section.placed_share * deposit
            rows.append(row)
        retained = retained - stage_cession
    schema = {
        "treaty_id": pl.String,
        "inception_date": pl.Date,
        "treaty_type": pl.String,
        "currency": pl.String,
        "gross_written": pl.Float64,
        "gross_earned": pl.Float64,
        "retained_written": pl.Float64,
        "retained_earned": pl.Float64,
        "ceded_premium": pl.Float64,
        "commission": pl.Float64,
        "deposit_premium": pl.Float64,
    }
    return PremiumApplication(pl.DataFrame(rows, schema=schema))
