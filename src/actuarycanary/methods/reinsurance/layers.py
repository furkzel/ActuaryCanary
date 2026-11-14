"""Layer arithmetic of the non-proportional treaties (MT21, CV09; decisions 0400 to 0402).

A unit is what the terms apply to: one claim (risk excess of loss), one event (claims with the
same event code) or all claims of the contract period (stop loss, aggregate excess of loss).
The layer works on the cumulative amounts of the unit at every valuation date the data hold:

- paid: each payment increment is deflated to inception prices with the deflator d of its
  month (1 without an index clause or under the occurrence-date clause), the layer is applied to
  the cumulative deflated payments, and each ceded increment is inflated back;
- incurred: the case reserve is valued with the deflator of the valuation date (an
  approximation of a future payment), so that ceded reserve = (layer(paid' + reserve * d) -
  layer(paid')) / d.

A unit's ceded amount is shared among its claims in proportion to their amounts (CV09). The
aggregate deductible and limit of a section work on the ceded incurred of its units in the
order in which the units are first hit; ceded paid follows ceded incurred in proportion.
"""

from dataclasses import dataclass

import numpy as np
import polars as pl


@dataclass(frozen=True)
class LayerUse:
    """Use of one section's layer at the last valuation date (100 per cent, before placed share)."""

    units_hit: int
    units_exhausted: int  # units whose ceded amount reached the limit
    ceded_before_aggregate: float
    aggregate_deductible_used: float
    ceded_after_aggregate: float
    aggregate_limit: float | None
    aggregate_exhausted: bool
    largest_unit_ceded: float


def _layer(x: np.ndarray, retention: np.ndarray, limit: np.ndarray) -> np.ndarray:
    return np.minimum(limit, np.maximum(0.0, x - retention))


def unit_amounts(rows: pl.DataFrame) -> pl.DataFrame:
    """Cumulative unit amounts and the layer at each date a member of the unit moves.

    `rows` holds one row per claim and valuation date with the columns unit, claim, day, paid,
    incurred, deflator, retention, limit and order (the unit's first occurrence, for ties).
    Returns one row per unit and day with the gross unit totals (u_paid, u_incurred) and the
    ceded amounts at 100 per cent (c_paid, c_incurred).
    """
    f = rows.sort(["claim", "day"]).with_columns(
        dp=pl.col("paid") - pl.col("paid").shift(1).over("claim").fill_null(0.0),
        dr=(pl.col("incurred") - pl.col("paid"))
        - (pl.col("incurred") - pl.col("paid")).shift(1).over("claim").fill_null(0.0),
    )
    ud = (
        f.group_by(["unit", "day"])
        .agg(
            pl.col("dp").sum(),
            (pl.col("dp") * pl.col("deflator")).sum().alias("dpd"),
            pl.col("dr").sum(),
            pl.col("deflator").first(),
            pl.col("retention").first(),
            pl.col("limit").first(),
            pl.col("order").first(),
        )
        .sort(["unit", "day"])
        .with_columns(
            pl.col("dp").cum_sum().over("unit").alias("u_paid"),
            pl.col("dpd").cum_sum().over("unit").alias("u_paid_deflated"),
            pl.col("dr").cum_sum().over("unit").alias("u_reserve"),
        )
    )
    d = ud["deflator"].to_numpy()
    ret, lim = ud["retention"].to_numpy(), ud["limit"].to_numpy()
    paid_d = ud["u_paid_deflated"].to_numpy()
    layer_paid_d = _layer(paid_d, ret, lim)
    layer_incurred_d = _layer(paid_d + ud["u_reserve"].to_numpy() * d, ret, lim)
    ud = ud.with_columns(
        pl.Series("lp", layer_paid_d), pl.Series("ceded_reserve_d", layer_incurred_d - layer_paid_d)
    ).with_columns(
        ((pl.col("lp") - pl.col("lp").shift(1).over("unit").fill_null(0.0)) / pl.col("deflator"))
        .cum_sum()
        .over("unit")
        .alias("c_paid"),
    )
    return ud.with_columns(
        (pl.col("u_paid") + pl.col("u_reserve")).alias("u_incurred"),
        (pl.col("c_paid") + pl.col("ceded_reserve_d") / pl.col("deflator")).alias("c_incurred"),
    ).select(["unit", "day", "order", "limit", "u_paid", "u_incurred", "c_paid", "c_incurred"])


def apply_aggregate(
    ud: pl.DataFrame, deductible: float | None, limit: float | None
) -> tuple[pl.DataFrame, LayerUse]:
    """Aggregate deductible and limit over the units of one section (CV09, decision 0402).

    The units enter in the order of the first date with a positive ceded amount (then their
    first occurrence, then the unit number); at every date the cumulative ceded incurred of the
    units in that order passes through the aggregate terms, so the unit that crosses a term gets
    the part that fits. Ceded paid of a unit is its ceded incurred after the terms times its
    paid share before them.
    """
    aad = 0.0 if deductible is None else float(deductible)
    aal = np.inf if limit is None else float(limit)
    days = np.sort(ud["day"].unique().to_numpy())
    hit = ud.filter(pl.col("c_incurred") > 0)
    exhausted = int(
        ud.filter(pl.col("c_incurred") >= pl.col("limit") * (1 - 1e-12))["unit"].n_unique()
    )
    if hit.height == 0:
        use = LayerUse(0, exhausted, 0.0, 0.0, 0.0, limit, False, 0.0)
        return ud.with_columns(a_paid=pl.lit(0.0), a_incurred=pl.lit(0.0)), use
    first = (
        hit.group_by("unit")
        .agg(pl.col("day").min().alias("first_hit"), pl.col("order").first())
        .sort(["first_hit", "order", "unit"])
    )
    units = first["unit"].to_numpy()
    position = {int(u): i for i, u in enumerate(units)}
    inc = np.zeros((len(units), len(days)))
    paid = np.zeros((len(units), len(days)))
    sub = ud.filter(pl.col("unit").is_in(units.tolist()))
    u_index = np.array([position[int(u)] for u in sub["unit"].to_numpy()])
    d_index = np.searchsorted(days, sub["day"].to_numpy())
    inc[u_index, d_index] = sub["c_incurred"].to_numpy()
    paid[u_index, d_index] = sub["c_paid"].to_numpy()
    present = np.zeros_like(inc, dtype=bool)
    present[u_index, d_index] = True
    for m in (inc, paid):  # carry each unit's last amount forward to the dates it does not move
        last = np.where(present, np.arange(len(days))[None, :], -1)
        np.maximum.accumulate(last, axis=1, out=last)
        m[:] = np.where(last >= 0, np.take_along_axis(m, np.maximum(last, 0), axis=1), 0.0)
    cumulative = np.cumsum(inc, axis=0)
    through = np.clip(cumulative - aad, 0.0, aal)
    after = np.diff(np.vstack([np.zeros((1, len(days))), through]), axis=0)
    after_paid = np.divide(after * paid, inc, out=np.zeros_like(after), where=inc > 0)
    a_inc = np.zeros(sub.height)
    a_inc[:] = after[u_index, d_index]
    a_paid = after_paid[u_index, d_index]
    sub = sub.with_columns(pl.Series("a_incurred", a_inc), pl.Series("a_paid", a_paid))
    rest = ud.filter(~pl.col("unit").is_in(units.tolist())).with_columns(
        a_paid=pl.lit(0.0), a_incurred=pl.lit(0.0)
    )
    before = float(inc[:, -1].sum())
    total_after = float(through[-1, -1])
    use = LayerUse(
        units_hit=len(units),
        units_exhausted=exhausted,
        ceded_before_aggregate=before,
        aggregate_deductible_used=min(aad, before),
        ceded_after_aggregate=total_after,
        aggregate_limit=limit,
        aggregate_exhausted=bool(np.isfinite(aal) and total_after >= aal * (1 - 1e-12)),
        largest_unit_ceded=float(inc[:, -1].max()),
    )
    return pl.concat([sub, rest.select(sub.columns)]).sort(["unit", "day"]), use


def layer_use(ud: pl.DataFrame) -> LayerUse:
    """Layer use of a section without aggregate terms, at the last date of each unit."""
    last = ud.sort("day").group_by("unit").agg(pl.col("c_incurred").last(), pl.col("limit").last())
    ceded = last["c_incurred"].to_numpy()
    exhausted = int((ceded >= last["limit"].to_numpy() * (1 - 1e-12)).sum())
    total = float(ceded.sum())
    return LayerUse(
        units_hit=int((ceded > 0).sum()),
        units_exhausted=exhausted,
        ceded_before_aggregate=total,
        aggregate_deductible_used=0.0,
        ceded_after_aggregate=total,
        aggregate_limit=None,
        aggregate_exhausted=False,
        largest_unit_ceded=float(ceded.max()) if len(ceded) else 0.0,
    )


def share_to_claims(rows: pl.DataFrame, ud: pl.DataFrame, per_claim: bool) -> pl.DataFrame:
    """Ceded paid and incurred of each row (100 per cent) from the unit amounts.

    A unit of one claim passes its amounts on; a unit of several claims shares them in
    proportion to the claims' paid and incurred at the date (CV09). The ceded reserve of a row
    is kept between zero and the row's reserve, and ceded paid between zero and its paid.
    """
    out = rows.join(
        ud.select(["unit", "day", "u_paid", "u_incurred", "a_paid", "a_incurred"]),
        on=["unit", "day"],
        how="left",
    )
    if per_claim:
        cp = out["a_paid"].to_numpy()
        ci = out["a_incurred"].to_numpy()
    else:
        up, ui = out["u_paid"].to_numpy(), out["u_incurred"].to_numpy()
        cp = np.divide(
            out["a_paid"].to_numpy() * out["paid"].to_numpy(),
            up,
            out=np.zeros(out.height),
            where=up > 0,
        )
        ci = np.divide(
            out["a_incurred"].to_numpy() * out["incurred"].to_numpy(),
            ui,
            out=np.zeros(out.height),
            where=ui > 0,
        )
    paid = out["paid"].to_numpy()
    reserve = out["incurred"].to_numpy() - paid
    cp = np.clip(cp, 0.0, np.maximum(paid, 0.0))
    cr = np.clip(ci - cp, 0.0, np.maximum(reserve, 0.0))
    return out.select("row").with_columns(
        pl.Series("ceded_paid", cp), pl.Series("ceded_incurred", cp + cr)
    )
