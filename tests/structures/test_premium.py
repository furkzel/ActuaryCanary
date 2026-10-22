"""PR02 earned premium, PR03 unearned premium and CV04 earned exposure, by hand.

Fixture: policy P1 covers 2024-07-01 to 2025-07-01 (365 days). WRITTEN 3650 on 1 July earns
10 a day; an ENDORSEMENT of 2730 effective 1 October earns 10 a day over the remaining 273
days; a CANCELLATION of -1810 effective 1 January 2025 earns -10 a day over the last 181 days.
Together they earn 4570 = the written premium of the expired policy.
"""

from datetime import date, timedelta

import polars as pl
import pytest
from hypothesis import given
from hypothesis import strategies as st

from actuarycanary.convert.bases import BasisUnavailableError, ReinsuranceBasis, ValueBasis
from actuarycanary.io.excel import SOURCE_ROW
from actuarycanary.structures.periods import Period, month_end
from actuarycanary.structures.premium import (
    PremiumError,
    PremiumSettings,
    earned_exposure,
    earned_premium,
    unearned_premium,
)
from tests.convert.fixtures import market

CUT_OFF = date(2025, 7, 31)
# transaction, type, booking, effective, amount
TRANSACTIONS = [
    ("T1", "WRITTEN", date(2024, 7, 1), date(2024, 7, 1), 3650.0),
    ("T2", "ENDORSEMENT", date(2024, 10, 1), date(2024, 10, 1), 2730.0),
    ("T3", "CANCELLATION", date(2025, 1, 1), date(2025, 1, 1), -1810.0),
    ("T4", "COMMISSION", date(2024, 7, 1), date(2024, 7, 1), 500.0),  # not premium
    ("T5", "CEDED_PREMIUM", date(2024, 7, 1), date(2024, 7, 1), 1825.0),
    ("T6", "UNMAPPED", date(2024, 7, 1), date(2024, 7, 1), 99.0),  # excluded (DV-PRM-04)
]
MONTHLY = [310, 310, 300, 620, 600, 620, 310, 280, 310, 300, 310, 300]  # 2024-07 to 2025-06


def _premiums(rows: list[tuple] = TRANSACTIONS, policy: str = "P1", currency: str = "TRY"):
    return pl.DataFrame(
        {
            "transaction_id": [r[0] for r in rows],
            "policy_id": [policy] * len(rows),
            "type": [r[1] for r in rows],
            "booking_date": [r[2] for r in rows],
            "effective_date": [r[3] for r in rows],
            "amount": [r[4] for r in rows],
            "currency": [currency] * len(rows),
            SOURCE_ROW: list(range(2, len(rows) + 2)),
        }
    )


def _policies(**extra) -> pl.DataFrame:
    data = {
        "policy_id": ["P1"],
        "start_date": [date(2024, 7, 1)],
        "end_date": [date(2025, 7, 1)],
        "segment": ["NON_LIFE"],
        "line": ["MOTOR_OD"],
        SOURCE_ROW: [2],
    }
    return pl.DataFrame({**data, **{k: [v] for k, v in extra.items()}})


def _earned(**settings) -> dict[str, float]:
    given = {"period": Period.MONTH, "cut_off": CUT_OFF} | settings
    result = earned_premium(_premiums(), _policies(), PremiumSettings(**given))
    return dict(zip(result.frame["period"], result.frame["earned_premium"], strict=True))


def test_pr02_gross_earned_premium_by_month() -> None:
    """Only the written types of PR01 count: commission, ceded and unmapped rows are left out."""
    earned = _earned()
    labels = [f"2024-{m:02d}" for m in range(7, 13)] + [f"2025-{m:02d}" for m in range(1, 7)]
    assert [earned[label] for label in labels] == pytest.approx(MONTHLY)
    assert sum(earned.values()) == pytest.approx(4570.0)  # written premium of the expired policy


def test_pr02_ceded_and_net_earned_premium() -> None:
    ceded = _earned(reinsurance_basis=ReinsuranceBasis.CEDED)
    net = _earned(reinsurance_basis=ReinsuranceBasis.NET)
    assert ceded["2024-07"] == pytest.approx(155.0) and sum(ceded.values()) == pytest.approx(1825)
    assert net["2024-07"] == pytest.approx(155.0)
    assert sum(net.values()) == pytest.approx(4570.0 - 1825.0)


def test_cv03_ceded_and_net_premium_need_ceded_rows() -> None:
    only_gross = _premiums(TRANSACTIONS[:3])
    for basis in (ReinsuranceBasis.CEDED, ReinsuranceBasis.NET):
        with pytest.raises(BasisUnavailableError, match="CEDED_PREMIUM.*CV03"):
            earned_premium(
                only_gross, _policies(), PremiumSettings(reinsurance_basis=basis, cut_off=CUT_OFF)
            )


def test_pr02_facts_booked_after_the_cut_off_are_ignored_and_later_periods_are_not_shown() -> None:
    earned = _earned(cut_off=date(2024, 12, 31))
    assert list(earned) == [f"2024-{m:02d}" for m in range(7, 13)]
    assert list(earned.values()) == pytest.approx(MONTHLY[:6])  # no cancellation yet


def test_cv04_periods_quarter_and_fiscal_year_labels() -> None:
    quarters = _earned(period=Period.QUARTER)
    assert quarters == pytest.approx(
        {"2024-Q3": 920.0, "2024-Q4": 1840.0, "2025-Q1": 900.0, "2025-Q2": 910.0}
    )
    fiscal = _earned(period=Period.YEAR, fiscal_year_start_month=7)
    assert fiscal == pytest.approx({"2024": 4570.0})  # July 2024 to June 2025
    calendar_years = _earned(period=Period.YEAR)
    assert calendar_years == pytest.approx({"2024": 2760.0, "2025": 1810.0})


def test_pr02_a_policy_that_is_not_in_policies_earns_nothing_and_is_listed() -> None:
    premiums = pl.concat(
        [
            _premiums(),
            _premiums(TRANSACTIONS[:1], policy="P9").with_columns(
                pl.lit("X1").alias("transaction_id"), pl.lit(40, dtype=pl.Int64).alias(SOURCE_ROW)
            ),
        ]
    )
    result = earned_premium(premiums, _policies(), PremiumSettings(cut_off=CUT_OFF))
    assert result.frame["earned_premium"].sum() == pytest.approx(4570.0)
    assert [(f.rule, f.count, f.rows) for f in result.findings] == [("DV-PRM-06", 1, (40,))]


def test_pr02_an_empty_earning_interval_earns_the_whole_amount_on_its_start() -> None:
    policies = _policies(end_date=date(2024, 7, 1))  # start on end: DV-POL-04
    result = earned_premium(_premiums(TRANSACTIONS[:1]), policies, PremiumSettings(cut_off=CUT_OFF))
    assert result.frame["period"].to_list() == ["2024-07"]
    assert result.frame["earned_premium"].to_list() == [3650.0]


def test_pr02_a_transaction_effective_before_the_policy_start_earns_from_the_start() -> None:
    rows = [("T1", "WRITTEN", date(2024, 6, 15), date(2024, 6, 20), 3650.0)]
    result = earned_premium(_premiums(rows), _policies(), PremiumSettings(cut_off=CUT_OFF))
    assert result.frame["period"][0] == "2024-07"
    assert result.frame["earned_premium"].sum() == pytest.approx(3650.0)


def test_cv01_premium_in_a_foreign_currency_is_converted_at_the_booking_date_rate() -> None:
    rates = market(
        [
            ("USD/TRY", "FX_SPOT", date(2024, 7, 1), 30.0),
            ("USD/TRY", "FX_SPOT", date(2024, 10, 1), 40.0),
            ("USD/TRY", "FX_SPOT", date(2025, 1, 1), 50.0),
        ]
    )
    result = earned_premium(
        _premiums(TRANSACTIONS[:3], currency="USD"),
        _policies(),
        PremiumSettings(cut_off=CUT_OFF, reporting_currency="TRY"),
        rates,
    )
    earned = dict(zip(result.frame["period"], result.frame["earned_premium"], strict=True))
    assert earned["2024-07"] == pytest.approx(310 * 30)
    assert earned["2024-10"] == pytest.approx(310 * 30 + 310 * 40)
    assert earned["2025-01"] == pytest.approx(310 * 30 + 310 * 40 - 310 * 50)
    assert result.frame["currency"].unique().to_list() == ["TRY"]
    assert result.not_converted.height == 0 and result.flagged == {}


def test_cv01_without_market_data_foreign_premium_is_reported_apart() -> None:
    result = earned_premium(
        _premiums(TRANSACTIONS[:3], currency="USD"),
        _policies(),
        PremiumSettings(cut_off=CUT_OFF, reporting_currency="TRY"),
    )
    assert result.frame.height == 0
    assert result.not_converted.to_dicts() == [{"currency": "USD", "rows": 3, "amount": 4570.0}]
    assert [(f.rule, f.count) for f in result.findings] == [("CV01", 3)]


def test_cv01_original_currency_view_keeps_each_currency_apart() -> None:
    premiums = pl.concat(
        [
            _premiums(TRANSACTIONS[:1], currency="TRY"),
            _premiums(TRANSACTIONS[:1], currency="USD").with_columns(
                pl.lit("U1").alias("transaction_id")
            ),
        ]
    )
    result = earned_premium(premiums, _policies(), PremiumSettings(cut_off=CUT_OFF))
    assert sorted(result.frame["currency"].unique().to_list()) == ["TRY", "USD"]
    assert result.frame["earned_premium"].sum() == pytest.approx(7300.0)


def test_cv02_premium_is_restated_from_its_booking_month() -> None:
    index = market(
        [
            ("CPI_TR", "PRICE_INDEX", date(2024, 7, 15), 200.0),
            ("CPI_TR", "PRICE_INDEX", date(2024, 10, 15), 250.0),
            ("CPI_TR", "PRICE_INDEX", date(2025, 7, 15), 300.0),
        ]
    )
    result = earned_premium(
        _premiums(TRANSACTIONS[:3]),
        _policies(),
        PremiumSettings(
            cut_off=CUT_OFF, reporting_currency="TRY", value_basis=ValueBasis.INFLATION_ADJUSTED
        ),
        index,
    )
    earned = dict(zip(result.frame["period"], result.frame["earned_premium"], strict=True))
    assert earned["2024-07"] == pytest.approx(310 * 1.5)
    assert earned["2024-10"] == pytest.approx(310 * 1.5 + 310 * 1.2)
    assert sum(earned.values()) == pytest.approx(3650 * 1.5 + (2730 - 1810) * 1.2)


def test_cv02_the_adjusted_basis_needs_a_reporting_currency_and_market_data() -> None:
    adjusted = PremiumSettings(cut_off=CUT_OFF, value_basis=ValueBasis.INFLATION_ADJUSTED)
    with pytest.raises(PremiumError, match="reporting currency"):
        earned_premium(_premiums(), _policies(), adjusted)
    with pytest.raises(PremiumError, match="market data"):
        earned_premium(
            _premiums(), _policies(), adjusted.model_copy(update={"reporting_currency": "TRY"})
        )


def test_pr03_unearned_premium_by_hand() -> None:
    settings = PremiumSettings()
    at = date(2024, 12, 31)
    result = unearned_premium(_premiums(), _policies(), settings, at)
    assert result.frame["unearned_premium"].to_list() == pytest.approx([3620.0])  # 1810 + 1810
    assert unearned_premium(_premiums(), _policies(), settings, CUT_OFF).frame[
        "unearned_premium"
    ].to_list() == pytest.approx([0.0])


def test_pr03_written_to_date_equals_earned_plus_unearned_at_every_month_end() -> None:
    gross = _premiums(TRANSACTIONS[:3])
    for month in (7, 10, 13, 16, 19):
        at = month_end(2024 * 12 + month - 1)
        written = gross.filter(pl.col("booking_date") <= at)["amount"].sum()
        earned = earned_premium(gross, _policies(), PremiumSettings(cut_off=at)).frame
        unearned = unearned_premium(gross, _policies(), PremiumSettings(), at).frame
        total = float(earned["earned_premium"].sum()) + float(unearned["unearned_premium"].sum())
        assert total == pytest.approx(float(written))


def test_pr03_unearned_premium_is_a_stock_converted_at_the_period_end_rate() -> None:
    rates = market([("USD/TRY", "FX_PERIOD_END", date(2024, 12, 31), 36.0)])
    result = unearned_premium(
        _premiums(TRANSACTIONS[:3], currency="USD"),
        _policies(),
        PremiumSettings(reporting_currency="TRY"),
        date(2024, 12, 31),
        rates,
    )
    assert result.frame["unearned_premium"].to_list() == pytest.approx([3620.0 * 36.0])


def test_cv04_earned_exposure_counts_days_of_cover_over_365_25() -> None:
    policies = pl.DataFrame(
        {
            "policy_id": ["A", "B", "C", "D", "E"],
            "start_date": [
                date(2024, 1, 1),
                date(2024, 7, 1),
                date(2024, 3, 1),
                None,
                date(2024, 1, 1),
            ],
            "end_date": [
                date(2025, 1, 1),
                date(2025, 7, 1),
                date(2024, 3, 1),
                date(2025, 1, 1),
                date(2025, 1, 1),
            ],
            "cancellation_date": [None, date(2025, 1, 1), None, None, None],
            "exposure_units": [None, 2.0, 1.0, 1.0, 3.0],
            "segment": ["S"] * 5,
            "line": ["L"] * 5,
        }
    )
    result = earned_exposure(policies, PremiumSettings(period=Period.YEAR), date(2025, 12, 31))
    by_year = dict(zip(result["period"], result["earned_exposure"], strict=True))
    # A: 366 days of 2024 (CV04); B: 2 units from July to its cancellation on 2025-01-01
    # (184 days, all 2024); C empty and D without start earn nothing; E: 3 units, 366 days
    assert by_year == pytest.approx({"2024": (366 + 2 * 184 + 3 * 366) / 365.25})


def test_cv04_exposure_is_cut_at_the_cut_off() -> None:
    policies = pl.DataFrame(
        {
            "policy_id": ["A"],
            "start_date": [date(2024, 1, 1)],
            "end_date": [date(2025, 1, 1)],
            "segment": ["S"],
            "line": ["L"],
        }
    )
    result = earned_exposure(policies, PremiumSettings(period=Period.QUARTER), date(2024, 6, 15))
    assert result["period"].to_list() == ["2024-Q1", "2024-Q2"]
    assert result["earned_exposure"].sum() == pytest.approx(182 / 365.25)  # to 2024-06-30


@st.composite
def _books(draw: st.DrawFn) -> tuple[pl.DataFrame, pl.DataFrame]:
    start = date(2023, 1, 1) + timedelta(days=draw(st.integers(0, 400)))
    end = start + timedelta(days=draw(st.integers(0, 400)))
    rows = []
    for k in range(draw(st.integers(1, 3))):
        kind = draw(st.sampled_from(["WRITTEN", "ENDORSEMENT", "CANCELLATION"]))
        effective = start + timedelta(days=draw(st.integers(-20, 450)))
        booking = effective - timedelta(days=draw(st.integers(0, 30)))
        rows.append((f"T{k}", kind, booking, effective, float(draw(st.integers(-5000, 5000)))))
    policies = _policies(start_date=start, end_date=end)
    return _premiums(rows), policies


@given(book=_books(), period=st.sampled_from(list(Period)))
def test_pr02_property_earned_over_all_periods_equals_written_for_expired_policies(
    book: tuple[pl.DataFrame, pl.DataFrame], period: Period
) -> None:
    premiums, policies = book
    settings = PremiumSettings(period=period, cut_off=date(2030, 12, 31))
    earned = earned_premium(premiums, policies, settings).frame["earned_premium"].sum()
    assert earned == pytest.approx(premiums["amount"].sum(), abs=1e-6)


@given(book=_books(), period=st.sampled_from(list(Period)))
def test_cv04_property_exposure_over_all_periods_is_days_of_cover_over_365_25(
    book: tuple[pl.DataFrame, pl.DataFrame], period: Period
) -> None:
    _, policies = book
    row = policies.row(0, named=True)
    days = max((row["end_date"] - row["start_date"]).days, 0)
    result = earned_exposure(policies, PremiumSettings(period=period), date(2030, 12, 31))
    assert result["earned_exposure"].sum() == pytest.approx(days / 365.25, abs=1e-9)


def test_cv02_premium_booked_before_the_index_starts_is_left_out_and_listed() -> None:
    index = market(
        [
            ("CPI_TR", "PRICE_INDEX", date(2024, 9, 15), 200.0),
            ("CPI_TR", "PRICE_INDEX", date(2025, 7, 15), 300.0),
        ]
    )
    result = earned_premium(
        _premiums(TRANSACTIONS[:3]),
        _policies(),
        PremiumSettings(
            cut_off=CUT_OFF, reporting_currency="TRY", value_basis=ValueBasis.INFLATION_ADJUSTED
        ),
        index,
    )
    # WRITTEN is booked in July, before the first index month: only the later two remain
    assert [(f.rule, f.count, f.rows) for f in result.findings] == [("CV02", 1, (2,))]
    assert result.frame["earned_premium"].sum() == pytest.approx((2730 - 1810) * 1.5)
