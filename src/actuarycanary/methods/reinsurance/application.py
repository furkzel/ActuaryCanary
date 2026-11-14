"""MT21 application step: a reinsurance programme applied to gross claim amounts.

Gross paid and incurred per claim and valuation date go in; ceded paid and ceded incurred per
claim, valuation date and section (treaty and contract period), net amounts per claim and
valuation date, the layer use of each section and the notes come out. The stages follow the
inuring order of CV09 (record 0604): facultative, surplus, quota share on the retained part,
risk excess of loss, event excess of loss, stop loss (and aggregate excess of loss), each on
what the stages before it leave. Decisions 0400 to 0402.
"""

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import polars as pl

from actuarycanary.methods.reinsurance.index import (
    INDEX_CLAUSES,
    OCCURRENCE_DATE,
    PAYMENT_BY_PAYMENT,
    FxLookup,
    PriceIndex,
)
from actuarycanary.methods.reinsurance.layers import (
    LayerUse,
    apply_aggregate,
    layer_use,
    share_to_claims,
    unit_amounts,
)
from actuarycanary.methods.reinsurance.terms import (
    RISKS_ATTACHING,
    STAGES,
    STOP_LOSS,
    SURPLUS,
    Excluded,
    Section,
)

EVENT_PER_CLAIM = "event cover applied per claim, an approximation"
NO_INDEX = (
    "index series {} missing from market: retention and limit used without indexation (DV-RTY-10)"
)
INDEXED = "index clause: {}"
RESERVE_AT_VALUATION_INDEX = (
    "case reserve valued with the index of the valuation date, an approximation"
)


@dataclass(frozen=True)
class ClaimBook:
    """Gross claim amounts and the attributes the scope rules need.

    valuations: claim_id, valuation_date, paid, incurred (cumulative, gross, original currency).
    claims: claim_id and, where known, occurrence_date, event_code, policy_id, line, segment,
    entity, currency. policies: policy_id, start_date, sum_insured, currency.
    """

    valuations: pl.DataFrame
    claims: pl.DataFrame
    policies: pl.DataFrame | None = None


@dataclass(frozen=True)
class Options:
    index_clause: str = PAYMENT_BY_PAYMENT
    price_index: dict[str, PriceIndex] = field(default_factory=dict)
    fx: FxLookup | None = None
    facultative_shares: dict[tuple[str, str], float] = field(default_factory=dict)
    earned_premium: dict[tuple[str, date], float] = field(default_factory=dict)  # stop loss
    deposit_premium: dict[tuple[str, date], float] = field(default_factory=dict)  # 100 % layer


@dataclass(frozen=True)
class SectionResult:
    section: Section
    use: LayerUse | None
    reinstatements_used: float | None
    reinstatement_premium: float | None
    claims_in_scope: int
    notes: tuple[str, ...]


@dataclass(frozen=True)
class Application:
    ceded: (
        pl.DataFrame
    )  # claim_id, valuation_date, treaty_id, inception_date, ceded_paid, ceded_incurred
    net: pl.DataFrame  # claim_id, valuation_date, gross_*, ceded_*, net_*
    sections: list[SectionResult]
    excluded: list[Excluded]
    out_of_scope: pl.DataFrame  # treaty_id, inception_date, claim_id, reason
    scope: pl.DataFrame = field(  # treaty_id, inception_date, claim_id: the claims in scope
        default_factory=lambda: pl.DataFrame(
            schema={"treaty_id": pl.String, "inception_date": pl.Date, "claim_id": pl.String}
        )
    )

    def ceded_at(self, day: date | None = None) -> pl.DataFrame:
        """Each claim's latest ceded amounts per section on or before `day` (default: all)."""
        frame = self.ceded if day is None else self.ceded.filter(pl.col("valuation_date") <= day)
        return (
            frame.sort("valuation_date")
            .group_by(["treaty_id", "inception_date", "claim_id"], maintain_order=True)
            .last()
        )

    def layer_frame(self) -> pl.DataFrame:
        rows = []
        for r in self.sections:
            s, use = r.section, r.use
            rows.append(
                {
                    "treaty_id": s.treaty_id,
                    "inception_date": s.inception,
                    "treaty_type": s.treaty_type,
                    "stage": s.stage,
                    "claims_in_scope": r.claims_in_scope,
                    "units_hit": None if use is None else use.units_hit,
                    "units_exhausted": None if use is None else use.units_exhausted,
                    "ceded_before_aggregate": None if use is None else use.ceded_before_aggregate,
                    "aggregate_deductible_used": None
                    if use is None
                    else use.aggregate_deductible_used,
                    "ceded_after_aggregate": None if use is None else use.ceded_after_aggregate,
                    "aggregate_limit": None if use is None else use.aggregate_limit,
                    "aggregate_exhausted": None if use is None else use.aggregate_exhausted,
                    "reinstatements_used": r.reinstatements_used,
                    "reinstatement_premium": r.reinstatement_premium,
                    "notes": "; ".join(r.notes),
                }
            )
        return pl.DataFrame(rows, infer_schema_length=None)


# ------------------------------------------------------------------ rows and scope


def _rows(book: ClaimBook) -> pl.DataFrame:
    """One row per claim and valuation date with the claim's attributes, sorted."""
    claims = book.claims
    for name, dtype in (
        ("occurrence_date", pl.Date),
        ("event_code", pl.String),
        ("policy_id", pl.String),
        ("line", pl.String),
        ("segment", pl.String),
        ("entity", pl.String),
        ("currency", pl.String),
    ):
        if name not in claims.columns:
            claims = claims.with_columns(pl.lit(None, dtype=dtype).alias(name))
    rows = (
        book.valuations.select(["claim_id", "valuation_date", "paid", "incurred"])
        .with_columns(pl.col("paid").cast(pl.Float64), pl.col("incurred").cast(pl.Float64))
        .join(claims.unique("claim_id", keep="first"), on="claim_id", how="left")
    )
    policies = book.policies
    if policies is not None and "policy_id" in policies.columns:
        keep = [c for c in ("policy_id", "start_date", "sum_insured") if c in policies.columns]
        pol = policies.select(keep).unique("policy_id", keep="first")
        if "currency" in policies.columns:
            pol = pol.join(
                policies.select(["policy_id", pl.col("currency").alias("policy_currency")]).unique(
                    "policy_id", keep="first"
                ),
                on="policy_id",
            )
        rows = rows.join(pol, on="policy_id", how="left")
    for name, dtype in (
        ("start_date", pl.Date),
        ("sum_insured", pl.Float64),
        ("policy_currency", pl.String),
    ):
        if name not in rows.columns:
            rows = rows.with_columns(pl.lit(None, dtype=dtype).alias(name))
    return (
        rows.sort(["claim_id", "valuation_date"])
        .with_row_index("row")
        .with_columns(pl.col("claim_id").rank("dense").cast(pl.Int64).alias("claim"))
    )


def _attribute_scope(section: Section) -> pl.Expr:
    expr = pl.lit(True)
    if section.lines is not None:
        expr &= pl.col("line").is_in(sorted(section.lines)).fill_null(False)
    if section.segment is not None:
        expr &= (pl.col("segment") == section.segment).fill_null(False)
    if section.entity is not None:
        expr &= (pl.col("entity") == section.entity).fill_null(False)
    return expr


def _scope(rows: pl.DataFrame, section: Section) -> tuple[np.ndarray, pl.DataFrame]:
    """Rows in the section's scope, and the claims that match it but lack the date its
    attachment basis needs (CV09)."""
    date_col = "start_date" if section.attachment_basis == RISKS_ATTACHING else "occurrence_date"
    attr = rows.select(_attribute_scope(section).alias("a"))["a"].to_numpy()
    day = rows[date_col]
    known = day.is_not_null().to_numpy()
    in_period = ((day >= section.inception) & (day < section.expiry)).fill_null(False).to_numpy()
    missing = rows.filter(pl.Series(attr & ~known)).select("claim_id").unique()
    reason = f"{date_col} missing for the {section.attachment_basis.lower()} basis"
    return attr & known & in_period, missing.with_columns(pl.lit(reason).alias("reason"))


def _fx_factor(options: Options, frm: np.ndarray, to: str, days: list[date | None]) -> np.ndarray:
    """Rate from each row's currency into `to` at the given dates; NaN where unknown."""
    out = np.ones(len(frm))
    other = np.flatnonzero((frm != to) & (frm != None))  # noqa: E711
    if len(other) == 0:
        return out
    cache: dict[tuple[str, object], float] = {}
    for i in other:
        day = days[i]
        key = (str(frm[i]), day)
        if key not in cache:
            rate = None if options.fx is None or day is None else options.fx(key[0], to, day)
            cache[key] = np.nan if rate is None else float(rate)
        out[i] = cache[key]
    return out


# ------------------------------------------------------------------ the stages


@dataclass
class _State:
    rows: pl.DataFrame
    base_paid: np.ndarray
    base_incurred: np.ndarray
    parts: list[pl.DataFrame]
    results: list[SectionResult]
    out: list[pl.DataFrame]
    scopes: list[pl.DataFrame] = field(default_factory=list)


def _proportional_share(
    section: Section, rows: pl.DataFrame, mask: np.ndarray, options: Options, notes: list[str]
) -> tuple[np.ndarray, pl.DataFrame]:
    share = np.zeros(rows.height)
    left_out = pl.DataFrame(
        {"claim_id": [], "reason": []}, schema={"claim_id": pl.String, "reason": pl.String}
    )
    if section.treaty_type == SURPLUS:
        assert section.retention is not None and section.number_of_lines is not None
        line = np.full(rows.height, section.retention)
        series = options.price_index.get(section.index_series or "")
        if section.index_series and series is None:
            notes.append(NO_INDEX.format(section.index_series))
        elif series is not None:  # the line at the price level of the policy start (0401)
            start = rows["start_date"].to_numpy().astype("datetime64[D]")
            known = ~np.isnat(start)
            scale = np.ones(rows.height)
            scale[known] = series.at(start[known]) / series.at_date(section.inception)
            line = line * scale
            notes.append(INDEXED.format("surplus line at the price level of the policy start"))
        insured = rows["sum_insured"].to_numpy().astype(float)
        currency = rows["policy_currency"].to_numpy()
        currency = np.where(currency == None, rows["currency"].to_numpy(), currency)  # noqa: E711
        rate = _fx_factor(options, currency, section.currency, rows["start_date"].to_list())
        insured = insured * rate
        usable = mask & np.isfinite(insured) & (insured > 0)
        no_si = mask & ~usable
        capacity = section.number_of_lines * line
        share[usable] = (
            np.clip(insured[usable] - line[usable], 0.0, capacity[usable]) / insured[usable]
        )
        if no_si.any():
            missing = rows.filter(pl.Series(no_si)).select("claim_id").unique()
            notes.append(
                f"surplus not applied to {missing.height} claims without a usable sum insured"
            )
            left_out = missing.with_columns(pl.lit("no usable sum insured").alias("reason"))
    elif section.treaty_type == "QUOTA_SHARE":
        assert section.cession_share is not None
        share[mask] = section.cession_share
    else:  # FACULTATIVE: shares per policy (from the policy-level movements, decision 0400)
        policy = rows["policy_id"].to_numpy()
        for i in np.flatnonzero(mask):
            share[i] = options.facultative_shares.get((section.treaty_id, str(policy[i])), 0.0)
        if not options.facultative_shares:
            notes.append("no policy-level cessions: facultative cover not applied")
    return share * section.placed_share, left_out


def _deflator_and_scale(
    section: Section, rows: pl.DataFrame, unit_day: np.ndarray, options: Options, notes: list[str]
) -> tuple[np.ndarray, np.ndarray]:
    """Deflator of each row (payment by payment) and scale of each row's unit terms
    (occurrence date), both 1 without an index clause (decision 0401)."""
    ones = np.ones(rows.height)
    if not section.index_series or section.treaty_type == STOP_LOSS:
        return ones, ones
    series = options.price_index.get(section.index_series)
    if series is None:
        notes.append(NO_INDEX.format(section.index_series))
        return ones, ones
    base = series.at_date(section.inception)
    if options.index_clause == OCCURRENCE_DATE:
        notes.append(INDEXED.format("terms at the price level of the occurrence date"))
        return ones, series.at(unit_day) / base
    notes.append(INDEXED.format("payment by payment"))
    notes.append(RESERVE_AT_VALUATION_INDEX)
    day = rows["valuation_date"].to_numpy().astype("datetime64[D]")
    return base / series.at(day), ones


def _layer_section(
    section: Section,
    rows: pl.DataFrame,
    mask: np.ndarray,
    state: _State,
    options: Options,
    notes: list[str],
) -> tuple[pl.DataFrame, LayerUse | None]:
    """Ceded paid and incurred (placed share applied) of the rows of one layer section."""
    sub_index = np.flatnonzero(mask)
    sub = rows[sub_index]
    occurrence = sub["occurrence_date"].to_numpy().astype("datetime64[D]")
    rate = _fx_factor(
        options, sub["currency"].to_numpy(), section.currency, sub["occurrence_date"].to_list()
    )
    known_rate = np.isfinite(rate)
    if not known_rate.all():
        lost = sub.filter(pl.Series(~known_rate)).select("claim_id").unique()
        notes.append(
            f"{lost.height} claims without an exchange rate into {section.currency} left out"
        )
        state.out.append(
            _out(section, lost.with_columns(pl.lit("no exchange rate").alias("reason")))
        )
        sub_index, sub, occurrence, rate = (
            sub_index[known_rate],
            sub.filter(pl.Series(known_rate)),
            occurrence[known_rate],
            rate[known_rate],
        )
    retention = float(section.retention or 0.0)
    limit = np.inf if section.limit is None else float(section.limit)
    per_claim = True
    if section.stage == "EVENT_XL":
        codes = sub["event_code"]
        # the data carry no event code at all: per claim (MT21); otherwise a claim without a
        # code is not part of an event and the event cover leaves it alone (0403)
        if rows["event_code"].is_null().all():
            notes.append(EVENT_PER_CLAIM)
            unit = sub["claim"].to_numpy()
        else:
            coded = codes.is_not_null().to_numpy()
            if not coded.all():
                lost = sub.filter(pl.Series(~coded)).select("claim_id").unique()
                notes.append(
                    f"{lost.height} claims without an event code not covered by the event treaty"
                )
            sub_index, sub, occurrence, rate = (
                sub_index[coded],
                sub.filter(pl.Series(coded)),
                occurrence[coded],
                rate[coded],
            )
            unit = sub["event_code"].rank("dense").cast(pl.Int64).to_numpy()
            per_claim = False
    elif section.stage == "AGGREGATE":
        per_claim = False
        unit = np.zeros(sub.height, dtype=np.int64)
        if section.treaty_type == STOP_LOSS:
            premium = options.earned_premium.get(section.key)
            if premium is None or premium <= 0:
                notes.append("stop loss not applied: no earned premium in scope")
                return _empty_part(), None
            retention, limit = retention * premium, limit * premium
    else:
        unit = sub["claim"].to_numpy()
    if sub.height == 0:
        return _empty_part(), None
    unit_frame = pl.DataFrame({"unit": unit, "occ": occurrence})
    first = unit_frame.group_by("unit").agg(pl.col("occ").min().alias("unit_day"))
    unit_day = (
        unit_frame.join(first, on="unit", how="left")["unit_day"].to_numpy().astype("datetime64[D]")
    )
    deflator, scale = _deflator_and_scale(section, sub, unit_day, options, notes)
    paid = state.base_paid[sub_index] * rate
    incurred = state.base_incurred[sub_index] * rate
    frame = pl.DataFrame(
        {
            "row": sub["row"],
            "unit": unit,
            "claim": sub["claim"],
            "day": sub["valuation_date"],
            "paid": paid,
            "incurred": incurred,
            "deflator": deflator,
            "retention": retention * scale,
            "limit": limit * scale,
            "order": unit_day.astype(np.int64),
        }
    )
    ud = unit_amounts(frame)
    if section.has_aggregate_terms and section.stage != "AGGREGATE":
        ud, use = apply_aggregate(
            ud, section.aggregate_deductible, section.effective_aggregate_limit
        )
    else:
        use = layer_use(ud)
        ud = ud.with_columns(a_paid=pl.col("c_paid"), a_incurred=pl.col("c_incurred"))
    ceded = share_to_claims(frame, ud, per_claim)
    back = section.placed_share / rate
    return ceded.with_columns(
        pl.col("ceded_paid") * pl.Series(back), pl.col("ceded_incurred") * pl.Series(back)
    ), use


def _empty_part() -> pl.DataFrame:
    return pl.DataFrame(
        {"row": [], "ceded_paid": [], "ceded_incurred": []},
        schema={"row": pl.UInt32, "ceded_paid": pl.Float64, "ceded_incurred": pl.Float64},
    )


def _out(section: Section, frame: pl.DataFrame) -> pl.DataFrame:
    return frame.select(
        pl.lit(section.treaty_id).alias("treaty_id"),
        pl.lit(section.inception).alias("inception_date"),
        pl.col("claim_id").cast(pl.String),
        pl.col("reason").cast(pl.String),
    )


def _reinstatement(
    section: Section, use: LayerUse | None, options: Options
) -> tuple[float | None, float | None]:
    """Reinstatements used and reinstatement premium pro rata as to amount (CV09)."""
    if use is None or section.reinstatements is None or not section.limit:
        return None, None
    m, limit = float(section.reinstatements), float(section.limit)
    used = min(m * limit, use.ceded_after_aggregate)
    premium = options.deposit_premium.get(section.key)
    rp = None
    if section.reinstatement_rate is not None and premium is not None:
        rp = section.reinstatement_rate * section.placed_share * premium * used / limit
    return used / limit, rp


def apply_programme(
    sections: list[Section],
    book: ClaimBook,
    options: Options | None = None,
    excluded: list[Excluded] | None = None,
) -> Application:
    """Apply the sections in the CV09 inuring order to the gross amounts of `book`."""
    options = options or Options()
    if options.index_clause not in INDEX_CLAUSES:
        raise ValueError(f"index_clause must be one of {INDEX_CLAUSES}")
    rows = _rows(book)
    state = _State(
        rows,
        rows["paid"].to_numpy().astype(float).copy(),
        rows["incurred"].to_numpy().astype(float).copy(),
        [],
        [],
        [],
    )
    for stage in STAGES:
        members = [s for s in sections if s.stage == stage]
        if not members:
            continue
        stage_parts: list[tuple[Section, pl.DataFrame]] = []
        for section in members:
            notes: list[str] = list(section.labels)
            mask, missing = _scope(rows, section)
            if missing.height:
                state.out.append(_out(section, missing))
            use = None
            if section.is_proportional:
                share, left_out = _proportional_share(section, rows, mask, options, notes)
                if left_out.height:
                    state.out.append(_out(section, left_out))
                idx = np.flatnonzero(mask & (share != 0))
                part = pl.DataFrame(
                    {
                        "row": rows["row"].to_numpy()[idx],
                        "ceded_paid": share[idx] * state.base_paid[idx],
                        "ceded_incurred": share[idx] * state.base_incurred[idx],
                    }
                )
            else:
                part, use = _layer_section(section, rows, mask, state, options, notes)
            used, rp = _reinstatement(section, use, options)
            in_scope = rows.filter(pl.Series(mask)).select("claim_id").unique(maintain_order=True)
            claims = in_scope.height
            state.scopes.append(
                in_scope.select(
                    pl.lit(section.treaty_id).alias("treaty_id"),
                    pl.lit(section.inception).alias("inception_date"),
                    pl.col("claim_id").cast(pl.String),
                )
            )
            state.results.append(
                SectionResult(section, use, used, rp, claims, tuple(dict.fromkeys(notes)))
            )
            stage_parts.append((section, part))
        _close_stage(state, stage_parts)
    return _assemble(state, excluded or [])


def _close_stage(state: _State, stage_parts: list[tuple[Section, pl.DataFrame]]) -> None:
    """Cap what one stage cedes at what it works on, then reduce the amounts for the next."""
    n = state.rows.height
    total_paid, total_incurred = np.zeros(n), np.zeros(n)
    for _, part in stage_parts:
        r = part["row"].to_numpy().astype(np.int64)
        np.add.at(total_paid, r, part["ceded_paid"].to_numpy())
        np.add.at(total_incurred, r, part["ceded_incurred"].to_numpy())
    scale_paid = np.where(
        total_paid > np.abs(state.base_paid),
        np.abs(state.base_paid) / np.where(total_paid > 0, total_paid, 1.0),
        1.0,
    )
    scale_incurred = np.where(
        total_incurred > np.abs(state.base_incurred),
        np.abs(state.base_incurred) / np.where(total_incurred > 0, total_incurred, 1.0),
        1.0,
    )
    for section, part in stage_parts:
        r = part["row"].to_numpy().astype(np.int64)
        part = part.with_columns(
            pl.col("ceded_paid") * pl.Series(scale_paid[r]),
            pl.col("ceded_incurred") * pl.Series(scale_incurred[r]),
        )
        state.parts.append(
            part.with_columns(
                pl.lit(section.treaty_id).alias("treaty_id"),
                pl.lit(section.inception).alias("inception_date"),
                pl.lit(section.treaty_type).alias("treaty_type"),
            )
        )
    state.base_paid = state.base_paid - total_paid * scale_paid
    state.base_incurred = state.base_incurred - total_incurred * scale_incurred


def _assemble(state: _State, excluded: list[Excluded]) -> Application:
    rows = state.rows
    keys = rows.select(["row", "claim_id", "valuation_date"])
    schema = {
        "row": pl.UInt32,
        "ceded_paid": pl.Float64,
        "ceded_incurred": pl.Float64,
        "treaty_id": pl.String,
        "inception_date": pl.Date,
        "treaty_type": pl.String,
    }
    parts = [p.cast(schema) for p in state.parts]  # type: ignore[arg-type]
    long = pl.concat(parts) if parts else pl.DataFrame(schema=schema)
    ceded = (
        long.join(keys, on="row", how="left")
        .select(
            [
                "claim_id",
                "valuation_date",
                "treaty_id",
                "inception_date",
                "treaty_type",
                "ceded_paid",
                "ceded_incurred",
            ]
        )
        .sort(["treaty_id", "inception_date", "claim_id", "valuation_date"])
    )
    gross_paid = rows["paid"].to_numpy()
    gross_incurred = rows["incurred"].to_numpy()
    net = rows.select(
        "claim_id",
        "valuation_date",
        pl.col("paid").alias("gross_paid"),
        pl.col("incurred").alias("gross_incurred"),
    ).with_columns(
        pl.Series("ceded_paid", ceded_paid := gross_paid - state.base_paid),
        pl.Series("ceded_incurred", ceded_incurred := gross_incurred - state.base_incurred),
        # net = gross - ceded exactly (CV03), the same subtraction the views make
        pl.Series("net_paid", gross_paid - ceded_paid),
        pl.Series("net_incurred", gross_incurred - ceded_incurred),
    )
    out_schema = {
        "treaty_id": pl.String,
        "inception_date": pl.Date,
        "claim_id": pl.String,
        "reason": pl.String,
    }
    out = (
        pl.concat([o.cast(out_schema) for o in state.out])  # type: ignore[arg-type]
        if state.out
        else pl.DataFrame(schema=out_schema)
    )
    out = out.sort(["treaty_id", "inception_date", "claim_id"]).unique(
        ["treaty_id", "claim_id", "reason"], keep="first", maintain_order=True
    )
    scope_schema = {"treaty_id": pl.String, "inception_date": pl.Date, "claim_id": pl.String}
    scope = (
        pl.concat([f.cast(scope_schema) for f in state.scopes])  # type: ignore[arg-type]
        if state.scopes
        else pl.DataFrame(schema=scope_schema)
    )
    return Application(ceded, net, state.results, excluded, out, scope)
