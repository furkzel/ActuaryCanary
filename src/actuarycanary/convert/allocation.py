"""CV09: treaty-level ceded movements allocated to claims, policies or line and origin cells,
and the ceded fields of claim valuations on the CV03 1.1.0 net basis (decision 0403).

Precedence: a movement with a claim_id (claim types) or a policy_id (premium types) is given and
never re-allocated. The others are spread by weights:

- claim movements (CEDED_CLAIM_PAID, CEDED_CASE_RESERVE): the claims' computed ceded movement of
  the same treaty and kind in the booking month (the application of MT21). For a proportional
  treaty that is s_k g_k(Q) of CV09; for excess of loss the change of the expected ceded amount;
  an event code on the movement keeps the claims of that event;
- CEDED_PREMIUM: the policies in the treaty's scope by gross written premium booked in the month
  (proportional treaties) or gross premium earned in the month (non-proportional);
  RI_COMMISSION follows the weights of its treaty's ceded premium;
- REINSTATEMENT_PREMIUM: the line and origin cells of the claims the treaty ceded, by their
  ceded incurred at the booking date.

When the weights are zero, the fallback `aggregate` spreads the amount over the line and origin
cells in the treaty's scope by gross incurred at the booking month end (claims) or gross written
premium of the booking year (premium), labelled "aggregate allocation, an approximation"; the
fallback `unallocated` leaves it on the treaty. The parts of a movement add up to it to the cent,
the rounding remainder going to the largest part.
"""

from dataclasses import dataclass
from datetime import date

import numpy as np
import polars as pl

from actuarycanary.methods.reinsurance.application import Application, ClaimBook
from actuarycanary.methods.reinsurance.terms import Section

CLAIM_TYPES = ("CEDED_CLAIM_PAID", "CEDED_CASE_RESERVE")
PREMIUM_TYPES = ("CEDED_PREMIUM", "RI_COMMISSION", "REINSTATEMENT_PREMIUM")
AGGREGATE = "aggregate"
UNALLOCATED = "unallocated"
FALLBACKS = (AGGREGATE, UNALLOCATED)

GIVEN = "given"
BY_CEDED_MOVEMENT = "claims by their computed ceded movement of the month"
BY_WRITTEN = "policies by gross written premium of the month"
BY_EARNED = "policies by gross earned premium of the month"
BY_CEDED_INCURRED = "origin cells by the ceded incurred of the claims ceded"
APPROXIMATION = "aggregate allocation, an approximation"
NOT_ALLOCATED = "unallocated: no weights in scope"

ALLOCATION_SCHEMA = {
    "transaction_id": pl.String,
    "treaty_id": pl.String,
    "type": pl.String,
    "booking_date": pl.Date,
    "currency": pl.String,
    "target": pl.String,  # claim, policy, cell or treaty
    "claim_id": pl.String,
    "policy_id": pl.String,
    "line": pl.String,
    "origin_year": pl.Int64,
    "amount": pl.Float64,
    "method": pl.String,
}


@dataclass(frozen=True)
class Allocation:
    rows: pl.DataFrame  # ALLOCATION_SCHEMA, one row per part of a movement

    def summary(self) -> pl.DataFrame:
        """Amount by treaty, type and method (the allocation notes of M08)."""
        return (
            self.rows.group_by(["treaty_id", "type", "method"])
            .agg(pl.len().alias("parts"), pl.col("amount").sum())
            .sort(["treaty_id", "type", "method"])
        )


def split_to_cents(amount: float, weights: np.ndarray) -> np.ndarray:
    """`amount` in proportion to `weights`, rounded to cents, the remainder on the largest part."""
    total = float(weights.sum())
    parts = np.round(amount * weights / total, 2)
    if len(parts):
        parts[int(np.argmax(np.abs(parts)))] += round(amount - float(parts.sum()), 2)
    return np.round(parts, 2)


def _month(day: pl.Expr) -> pl.Expr:
    return day.dt.year().cast(pl.Int64) * 12 + day.dt.month().cast(pl.Int64)


def _ceded_movements(application: Application) -> pl.DataFrame:
    """Each claim's computed ceded paid flow and ceded reserve change per treaty and month."""
    ceded = application.ceded.sort(["treaty_id", "inception_date", "claim_id", "valuation_date"])
    reserve = pl.col("ceded_incurred") - pl.col("ceded_paid")
    keys = ["treaty_id", "inception_date", "claim_id"]
    return (
        ceded.with_columns(
            (pl.col("ceded_paid") - pl.col("ceded_paid").shift(1).over(keys).fill_null(0.0)).alias(
                "CEDED_CLAIM_PAID"
            ),
            (reserve - reserve.shift(1).over(keys).fill_null(0.0)).alias("CEDED_CASE_RESERVE"),
            _month(pl.col("valuation_date")).alias("month"),
        )
        .group_by(["treaty_id", "claim_id", "month"])
        .agg(pl.col("CEDED_CLAIM_PAID").sum(), pl.col("CEDED_CASE_RESERVE").sum())
    )


def _cells(book: ClaimBook) -> pl.DataFrame:
    """Line and origin year of each claim."""
    claims = book.claims
    line = pl.col("line") if "line" in claims.columns else pl.lit(None, dtype=pl.String)
    origin = (
        pl.col("occurrence_date").dt.year().cast(pl.Int64)
        if "occurrence_date" in claims.columns
        else pl.lit(None, dtype=pl.Int64)
    )
    return claims.select("claim_id", line.alias("line"), origin.alias("origin_year"))


def _in_scope(frame: pl.DataFrame, sections: list[Section], periods: bool = False) -> pl.DataFrame:
    """Rows of `frame` (with line, segment, entity where present) in any section's scope; with
    `periods`, also in the section's contract period on its attachment basis (claims)."""
    if not sections:
        return frame.head(0)
    expr = pl.lit(False)
    for s in sections:
        one = pl.lit(True)
        if periods:
            column = "start_date" if s.attachment_basis == "RISKS_ATTACHING" else "occurrence_date"
            if column not in frame.columns:
                continue
            one &= ((pl.col(column) >= s.inception) & (pl.col(column) < s.expiry)).fill_null(False)
        if s.lines is not None and "line" in frame.columns:
            one &= pl.col("line").is_in(sorted(s.lines)).fill_null(False)
        if s.segment is not None and "segment" in frame.columns:
            one &= (pl.col("segment") == s.segment).fill_null(False)
        if s.entity is not None and "entity" in frame.columns:
            one &= (pl.col("entity") == s.entity).fill_null(False)
        expr |= one
    return frame.filter(expr)


class _Allocator:
    def __init__(
        self,
        sections: list[Section],
        book: ClaimBook | None,
        application: Application | None,
        written: pl.DataFrame | None,
        fallback: str,
    ) -> None:
        if fallback not in FALLBACKS:
            raise ValueError(f"allocation_fallback must be one of {FALLBACKS}")
        self.by_treaty: dict[str, list[Section]] = {}
        for s in sections:
            self.by_treaty.setdefault(s.treaty_id, []).append(s)
        self.book = book
        self.fallback = fallback
        self.cells = _cells(book) if book is not None else None
        self.moves = _ceded_movements(application) if application is not None else None
        self.ceded = application.ceded_at() if application is not None else None
        self.written = (
            written.with_columns(_month(pl.col("booking_date")).alias("month"))
            if written is not None
            else None
        )
        self._tables: dict[str, tuple[dict[tuple, pl.DataFrame], str]] = {}
        self.premium_months: dict[str, set[int]] = {}

    # weights ---------------------------------------------------------------------------------

    def claim_weights(self, treaty: str, kind: str, month: int, event: str | None) -> pl.DataFrame:
        if self.moves is None:
            return pl.DataFrame(schema={"claim_id": pl.String, "w": pl.Float64})
        frame = self.moves.filter(
            (pl.col("treaty_id") == treaty) & (pl.col("month") == month) & (pl.col(kind) != 0)
        )
        if event is not None and self.book is not None and "event_code" in self.book.claims.columns:
            members = self.book.claims.filter(pl.col("event_code") == event).select("claim_id")
            frame = frame.join(members, on="claim_id", how="semi")
        return frame.select("claim_id", pl.col(kind).alias("w"))

    def premium_weights(
        self, treaty: str, month: int, line: str | None
    ) -> tuple[pl.DataFrame, str]:
        empty = pl.DataFrame(schema={"policy_id": pl.String, "line": pl.String, "w": pl.Float64})
        sections = self.by_treaty.get(treaty, [])
        if self.written is None or not sections:
            return empty, BY_WRITTEN
        if treaty not in self._tables:
            self._tables[treaty] = self._premium_table(treaty, sections)
        by_month, method = self._tables[treaty]
        frame = by_month.get((month, line) if line is not None else (month,), empty)
        return frame, method

    def _premium_table(
        self, treaty: str, sections: list[Section]
    ) -> tuple[dict[tuple, pl.DataFrame], str]:
        """Weights of the treaty's premium movements by booking month: gross written premium of
        the month (proportional) or gross premium earned in the month (non-proportional)."""
        assert self.written is not None
        scope = _in_scope(self.written, sections)
        if sections[0].is_proportional:
            frame = scope.group_by(["month", "policy_id", "line"]).agg(
                pl.col("amount").sum().alias("w")
            )
            method = BY_WRITTEN
        else:
            months = pl.DataFrame(
                {"month": sorted(self.premium_months.get(treaty, set()))},
                schema={"month": pl.Int64},
            )
            frame = self._earned_by_month(scope, months)
            method = BY_EARNED
        frame = frame.filter(pl.col("w") != 0).select("month", "policy_id", "line", "w")
        out: dict[tuple, pl.DataFrame] = {}
        for k, part in frame.partition_by("month", as_dict=True).items():
            out[(int(k[0]),)] = part.drop("month")  # type: ignore[arg-type]
        for k, part in frame.partition_by(["month", "line"], as_dict=True).items():
            out[(int(k[0]), k[1])] = part.drop("month")  # type: ignore[arg-type]
        return out, method

    @staticmethod
    def _earned_by_month(scope: pl.DataFrame, months: pl.DataFrame) -> pl.DataFrame:
        """Premium earned in each month pro rata by days of the policy term."""
        first = pl.date(((pl.col("month") - 1) // 12), ((pl.col("month") - 1) % 12) + 1, 1)
        months = months.with_columns(first.alias("m_start")).with_columns(
            pl.col("m_start").dt.offset_by("1mo").alias("m_end")
        )
        term = (pl.col("end_date") - pl.col("start_date")).dt.total_days()
        a = pl.max_horizontal(pl.col("start_date"), pl.col("m_start"))
        b = pl.min_horizontal(pl.col("end_date"), pl.col("m_end"))
        inside = (b - a).dt.total_days()
        return (
            scope.filter(term > 0)
            .select("policy_id", "line", "start_date", "end_date", "amount")
            .join(months, how="cross")
            .filter(
                (pl.col("start_date") < pl.col("m_end")) & (pl.col("end_date") > pl.col("m_start"))
            )
            .with_columns((pl.col("amount") * inside / term).alias("w"))
            .group_by(["month", "policy_id", "line"])
            .agg(pl.col("w").sum())
        )

    def aggregate_cells(
        self, treaty: str, day: date, claims: bool, effective: date | None = None
    ) -> pl.DataFrame:
        """Line and origin cells of the treaty's scope with their weight for the fallback: the
        sections whose period holds the movement's effective date, or all sections of the
        treaty; claims by the date of the section's attachment basis."""
        sections = self.by_treaty.get(treaty, [])
        if effective is not None:
            sections = [s for s in sections if s.inception <= effective < s.expiry] or sections
        empty = pl.DataFrame(schema={"line": pl.String, "origin_year": pl.Int64, "w": pl.Float64})
        if claims:
            if self.book is None or self.cells is None:
                return empty
            latest = (
                self.book.valuations.filter(pl.col("valuation_date") <= day)
                .sort("valuation_date")
                .group_by("claim_id")
                .last()
            )
            frame = latest.join(self.book.claims, on="claim_id", how="left")
            if self.book.policies is not None and "start_date" in self.book.policies.columns:
                starts = self.book.policies.select("policy_id", "start_date").unique("policy_id")
                if "policy_id" in frame.columns:
                    frame = frame.join(starts, on="policy_id", how="left")
            frame = _in_scope(frame, sections, periods=True)
            frame = frame.join(self.cells, on="claim_id", how="left", suffix="_cell")
            return (
                frame.group_by(["line", "origin_year"])
                .agg(pl.col("incurred").sum().alias("w"))
                .filter(pl.col("w") > 0)
            )
        if self.written is None:
            return empty
        scope = _in_scope(self.written, sections).filter(
            pl.col("booking_date").dt.year() == day.year
        )
        return (
            scope.group_by("line")
            .agg(pl.col("amount").sum().alias("w"))
            .with_columns(pl.lit(day.year, dtype=pl.Int64).alias("origin_year"))
            .filter(pl.col("w") > 0)
        )

    def reinstatement_cells(self, treaty: str, day: date) -> pl.DataFrame:
        if self.ceded is None or self.cells is None:
            return pl.DataFrame(
                schema={"line": pl.String, "origin_year": pl.Int64, "w": pl.Float64}
            )
        return (
            self.ceded.filter((pl.col("treaty_id") == treaty) & (pl.col("valuation_date") <= day))
            .join(self.cells, on="claim_id", how="left")
            .group_by(["line", "origin_year"])
            .agg(pl.col("ceded_incurred").sum().alias("w"))
            .filter(pl.col("w") > 0)
        )


class _Parts:
    """Columns of the allocation rows, filled part by part and made a frame once."""

    def __init__(self) -> None:
        self.columns: dict[str, list] = {k: [] for k in ALLOCATION_SCHEMA}

    def add(
        self, move: dict, target: str, method: str, amounts: np.ndarray, ids: dict[str, list]
    ) -> None:
        n = len(amounts)
        for name in ("transaction_id", "treaty_id", "type", "booking_date", "currency"):
            self.columns[name].extend([move.get(name)] * n)
        self.columns["target"].extend([target] * n)
        self.columns["method"].extend([method] * n)
        self.columns["amount"].extend(amounts.tolist())
        for name in ("claim_id", "policy_id", "line", "origin_year"):
            self.columns[name].extend(ids.get(name, [None] * n))

    def split(self, move: dict, weights: pl.DataFrame, target: str, method: str) -> None:
        amounts = split_to_cents(float(move["amount"]), weights["w"].to_numpy().astype(float))
        ids = {
            c: weights[c].to_list()
            for c in ("claim_id", "policy_id", "line", "origin_year")
            if c in weights.columns
        }
        self.add(move, target, method, amounts, ids)

    def single(self, move: dict, target: str, method: str, **ids: object) -> None:
        self.add(
            move,
            target,
            method,
            np.array([float(move["amount"])]),
            {k: [v] for k, v in ids.items()},
        )

    def frame(self) -> pl.DataFrame:
        return pl.DataFrame(self.columns, schema=ALLOCATION_SCHEMA)


def allocate(
    movements: pl.DataFrame,
    sections: list[Section],
    book: ClaimBook | None,
    application: Application | None,
    written: pl.DataFrame | None,
    fallback: str = AGGREGATE,
) -> Allocation:
    """Every ceded movement as given or allocated parts, with the method used (CV09)."""
    al = _Allocator(sections, book, application, written, fallback)
    frame = movements
    for name, dtype in (
        ("claim_id", pl.String),
        ("policy_id", pl.String),
        ("event_code", pl.String),
        ("line", pl.String),
        ("currency", pl.String),
    ):
        if name not in frame.columns:
            frame = frame.with_columns(pl.lit(None, dtype=dtype).alias(name))
    frame = frame.filter(pl.col("amount").is_not_null() & pl.col("booking_date").is_not_null())
    for (treaty,), part in frame.filter(pl.col("type").is_in(PREMIUM_TYPES)).group_by("treaty_id"):
        al.premium_months[str(treaty)] = set(
            part.select(_month(pl.col("booking_date")))["booking_date"].to_list()
        )
    parts = _Parts()
    for move in frame.iter_rows(named=True):
        kind = move["type"]
        day: date = move["booking_date"]
        month = day.year * 12 + day.month
        if kind in CLAIM_TYPES and move["claim_id"] is not None:
            parts.single(move, "claim", GIVEN, claim_id=move["claim_id"])
            continue
        if kind in PREMIUM_TYPES and move["policy_id"] is not None:
            parts.single(move, "policy", GIVEN, policy_id=move["policy_id"])
            continue
        weights, target, method = _weights(al, move, kind, month, day)
        if weights.height == 0 or float(weights["w"].sum()) == 0.0:
            claims = kind in CLAIM_TYPES
            if fallback == AGGREGATE:
                weights = al.aggregate_cells(
                    move["treaty_id"], day, claims, move.get("effective_date")
                )
                target, method = "cell", APPROXIMATION
            if weights.height == 0 or float(weights["w"].sum()) == 0.0:
                parts.single(move, "treaty", NOT_ALLOCATED)
                continue
        parts.split(move, weights, target, method)
    rows = parts.frame()
    return Allocation(rows)


def _weights(
    al: _Allocator, move: dict, kind: str, month: int, day: date
) -> tuple[pl.DataFrame, str, str]:
    treaty = move["treaty_id"]
    if kind in CLAIM_TYPES:
        weights = al.claim_weights(treaty, kind, month, move["event_code"])
        total = float(weights["w"].sum()) if weights.height else 0.0
        if weights.height and abs(total) <= 1e-9 * float(weights["w"].abs().sum()):
            weights = weights.head(0)  # weights that cancel out carry no direction
        return weights, "claim", BY_CEDED_MOVEMENT
    if kind == "REINSTATEMENT_PREMIUM":
        return al.reinstatement_cells(treaty, day), "cell", BY_CEDED_INCURRED
    weights, method = al.premium_weights(treaty, month, move["line"])
    return weights, "policy", method


def ceded_valuation_fields(
    valuations: pl.DataFrame, allocation: Allocation
) -> tuple[pl.DataFrame, bool]:
    """claim_valuations with the CV03 1.1.0 ceded fields.

    Fields already in the file are taken as given and nothing changes (`False` is returned).
    Without them, ceded paid and ceded reserve of each claim and valuation date are the given
    and allocated claim movements booked up to that date (CEDED_CASE_RESERVE is a change), and
    `ceded_source` says whether a value rests on given movements, on allocated ones or both.
    """
    if "ceded_paid_to_date" in valuations.columns or "ceded_reserve" in valuations.columns:
        return valuations, False
    claim_parts = allocation.rows.filter(
        pl.col("type").is_in(CLAIM_TYPES) & pl.col("claim_id").is_not_null()
    )
    if claim_parts.height == 0:
        return valuations, False
    steps = (
        claim_parts.group_by(["claim_id", "booking_date"])
        .agg(
            pl.col("amount").filter(pl.col("type") == "CEDED_CLAIM_PAID").sum().alias("dp"),
            pl.col("amount").filter(pl.col("type") == "CEDED_CASE_RESERVE").sum().alias("dr"),
            (pl.col("method") != GIVEN).any().alias("allocated"),
            (pl.col("method") == GIVEN).any().alias("given"),
        )
        .sort(["claim_id", "booking_date"])
        .with_columns(
            pl.col("dp").cum_sum().over("claim_id").alias("ceded_paid_to_date"),
            pl.col("dr").cum_sum().over("claim_id").alias("ceded_reserve"),
            pl.col("allocated").cum_max().over("claim_id"),
            pl.col("given").cum_max().over("claim_id"),
        )
    )
    out = (
        valuations.with_row_index("_order")
        .sort("valuation_date")
        .join_asof(
            steps.select(
                "claim_id",
                pl.col("booking_date").alias("valuation_date"),
                "ceded_paid_to_date",
                "ceded_reserve",
                "allocated",
                "given",
            ).sort("valuation_date"),
            on="valuation_date",
            by="claim_id",
            strategy="backward",
            check_sortedness=False,  # both sides sorted by date; polars cannot check with `by`
        )
        .sort("_order")
        .drop("_order")
        .with_columns(
            pl.col("ceded_paid_to_date").fill_null(0.0),
            pl.col("ceded_reserve").fill_null(0.0),
            pl.when(pl.col("allocated").fill_null(False) & pl.col("given").fill_null(False))
            .then(pl.lit("given and allocated"))
            .when(pl.col("allocated").fill_null(False))
            .then(pl.lit("allocated"))
            .otherwise(pl.lit("given"))
            .alias("ceded_source"),
        )
        .drop("allocated", "given")
    )
    return out, True
