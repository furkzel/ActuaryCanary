"""The extra inputs of the tier B reserving methods (record 0620).

MT15 and MT16 do not run on the triangles of the run. They need the non-nil reported counts
and the amounts of the ordinary claims, the catastrophe claims apart (CV08: a claim with an
event code), the severity at value-date prices when the price index is loaded, and the earned
exposure of each origin (CL05). They are built from the same feeds, rates and bases as the
triangles of the run, each set on first use.
"""

from dataclasses import dataclass, field
from datetime import date

import polars as pl

from actuarycanary.convert.bases import ValueBasis
from actuarycanary.convert.market import ConversionError, MarketData
from actuarycanary.convert.rates import DevelopmentRates
from actuarycanary.methods.seeding import RUN_SEED
from actuarycanary.structures.premium import PremiumSettings, earned_exposure
from actuarycanary.structures.triangles import (
    OriginAxis,
    Triangle,
    TriangleError,
    TriangleSet,
    TriangleSettings,
    build_triangles,
)

NIL = "CLOSED_NIL"
NOMINAL = ValueBasis.NOMINAL.value
ADJUSTED = ValueBasis.INFLATION_ADJUSTED.value
NO_CLAIMS = (
    "claims are not loaded: counts and catastrophe claims by accident period need claims.xlsx"
)


@dataclass
class TierBSource:
    """Triangles and exposure for MT15 and MT16, built on first use.

    `reason` is why they cannot be built (no claims, another origin axis); each getter then
    returns None and the reason is the one the methods report."""

    valuations: pl.DataFrame
    claims: pl.DataFrame | None
    settings: TriangleSettings
    rates: DevelopmentRates
    currency: str
    policies: pl.DataFrame | None
    market: MarketData | None
    price_index: str
    cut_off: date
    exposure_policies: pl.DataFrame | None = None
    reason: str = ""
    _cache: dict[tuple[str, str, tuple[str, ...], bool], tuple[TriangleSet | None, str]] = field(
        default_factory=dict
    )
    _exposure: dict[tuple[str, str], dict[str, float]] | None = None

    @property
    def indexed(self) -> bool:
        """The price index is loaded, so severity can be taken at value-date prices."""
        return self.market is not None and self.market.index(self.price_index) is not None

    def _frames(self, separate: bool) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
        """(claims, non-nil claims, catastrophe claims) as valuation rows. With `separate`
        the first two leave out the catastrophe claims; without it the third is empty."""
        assert self.claims is not None
        events = (
            self.claims.filter(
                pl.col("event_code").is_not_null()
                & (pl.col("event_code") != "UNKNOWN")
                & (pl.col("event_code") != "")
            )["claim_id"]
            if "event_code" in self.claims.columns
            else pl.Series("claim_id", [], dtype=self.claims["claim_id"].dtype)
        )
        latest = self.valuations.sort("valuation_date").group_by("claim_id").last()
        nil = latest.filter(pl.col("status") == NIL)["claim_id"]
        is_event = pl.col("claim_id").is_in(events.implode())
        regular = self.valuations.filter(~is_event) if separate else self.valuations
        non_nil = regular.filter(~pl.col("claim_id").is_in(nil.implode()))
        return regular, non_nil, self.valuations.filter(is_event & pl.lit(separate))

    def _build(
        self, kind: str, basis: str, frame: pl.DataFrame, measures: tuple[str, ...], separate: bool
    ) -> tuple[TriangleSet | None, str]:
        key = (kind, basis, measures, separate)
        if key not in self._cache:
            settings = self.settings.model_copy(update={"value_basis": ValueBasis(basis)})
            found: tuple[TriangleSet | None, str]
            if frame.height == 0:
                found = (None, "")
            else:
                try:
                    found = (
                        build_triangles(
                            frame,
                            self.claims,
                            settings,
                            self.rates,
                            self.currency,
                            policies=self.policies,
                            market=self.market,
                            price_index=self.price_index,
                            measures=measures,
                        ),
                        "",
                    )
                except (ConversionError, TriangleError) as error:
                    found = (None, f"the triangles of {kind} could not be built: {error}")
            self._cache[key] = found
        return self._cache[key]

    def counts(self, separate: bool = True) -> tuple[TriangleSet | None, str]:
        """Reported counts of the non-nil claims, without catastrophe claims if `separate`."""
        if self.reason:
            return None, self.reason
        return self._build(
            "counts", NOMINAL, self._frames(separate)[1], ("reported_count",), separate
        )

    def regular(
        self, basis: str, measures: tuple[str, ...], separate: bool = True
    ) -> tuple[TriangleSet | None, str]:
        """Amounts of the claims, without catastrophe claims if `separate`; nil claims are in
        (they pay nothing)."""
        if self.reason:
            return None, self.reason
        return self._build("regular", basis, self._frames(separate)[0], measures, separate)

    def catastrophe(self, basis: str, measures: tuple[str, ...]) -> tuple[TriangleSet | None, str]:
        """Amounts of the catastrophe claims; None when there are none."""
        if self.reason:
            return None, self.reason
        return self._build("catastrophe", basis, self._frames(True)[2], measures, True)

    def exposure(self, group: tuple[str, ...], origins: tuple[str, ...]) -> list[float] | None:
        """Earned exposure (CL05) of each origin, None when policies are not loaded or an
        origin has none."""
        if self.exposure_policies is None:
            return None
        if self._exposure is None:
            settings = PremiumSettings(
                period=self.settings.origin_period,
                fiscal_year_start_month=self.settings.fiscal_year_start_month,
                cut_off=self.cut_off,
            )
            frame = earned_exposure(self.exposure_policies, settings, self.cut_off)
            found: dict[tuple[str, str], dict[str, float]] = {}
            for segment, line, period, amount in frame.select(
                "segment", "line", "period", "earned_exposure"
            ).iter_rows():
                found.setdefault((segment, line), {})[str(period)] = float(amount)
            self._exposure = found
        known = self._exposure.get((group[0], group[1]), {})
        values = [known.get(o, 0.0) for o in origins]
        return values if all(v > 0 for v in values) else None


@dataclass(frozen=True)
class TierBInputs:
    """Everything the tier B methods take besides the run's own triangles. `source` is None
    when they are not wired (a plain `run_reserving` call), and then no tier B method runs."""

    source: TierBSource
    seed: int = RUN_SEED


def tier_b_source(
    valuations: pl.DataFrame,
    claims: pl.DataFrame | None,
    exposure_policies: pl.DataFrame | None,
    settings: TriangleSettings,
    rates: DevelopmentRates,
    currency: str,
    *,
    policies: pl.DataFrame | None,
    market: MarketData | None,
    price_index: str,
    cut_off: date,
) -> TierBSource:
    reason = ""
    if claims is None:
        reason = NO_CLAIMS
    elif settings.origin_axis is not OriginAxis.ACCIDENT:
        reason = (
            "counts and severity by accident period need the accident origin axis, and the "
            f"origin axis is {settings.origin_axis.value}"
        )
    return TierBSource(
        valuations,
        claims,
        settings,
        rates,
        currency,
        policies,
        market,
        price_index,
        cut_off,
        exposure_policies,
        reason,
    )


def group_triangle(
    found: TriangleSet | None, measure: str, group: tuple[str, ...]
) -> Triangle | None:
    """The triangle of `measure` for `group`, None when the set has none."""
    if found is None:
        return None
    return next(
        (t for t in found.triangles if t.measure == measure and t.group == group),
        None,
    )
