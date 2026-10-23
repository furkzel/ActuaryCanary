"""MT08 robust z-score flags: the hand fixture, the deviation fallbacks, groups and the
recall of injected payment outliers on the synthetic baseline."""

import math
from datetime import date

import polars as pl
import pytest

from actuarycanary.io.excel import SOURCE_ROW
from actuarycanary.methods.robust_z import RobustZ, robust_z_flags
from tests.methods.helpers import reserve_flag_shares
from tests.methods.medium import load_medium, medium

DAY = date(2024, 1, 31)


def _valuations(rows: list[tuple[str, date, float, float, str]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "claim_id": [r[0] for r in rows],
            "valuation_date": [r[1] for r in rows],
            "paid_to_date": [r[2] for r in rows],
            "case_reserve": [r[3] for r in rows],
            "currency": [r[4] for r in rows],
            SOURCE_ROW: list(range(2, len(rows) + 2)),
        },
        schema_overrides={"valuation_date": pl.Date},
    )


def _payments(logs: list[float], currency: str = "TRY") -> pl.DataFrame:
    """One claim per value, whose single row pays exp(value)."""
    return _valuations([(f"C{k:03d}", DAY, math.exp(y), 0.0, currency) for k, y in enumerate(logs)])


def _run(valuations: pl.DataFrame, **options) -> RobustZ:
    return robust_z_flags(valuations, None, {"TRY": 1.0}, variables=("paid_flow",), **options)


def test_fixture_one_to_thirty_and_sixty_give_one_flag() -> None:
    # median 16; |y - 16| has median 8; z(60) = 0.6745 x 44 / 8
    result = _run(_payments([*range(1, 31), 60]))
    assert result.flags.height == 1
    flag = result.flags.row(0, named=True)
    assert flag["claim_id"] == "C030"
    assert flag["z"] == pytest.approx(0.6745 * 44 / 8, rel=1e-12)
    assert flag["threshold"] == 3.5
    assert flag[SOURCE_ROW] == 32
    assert flag["reason"].startswith("payment of ")
    assert "robust z 3.71, threshold 3.5" in flag["reason"]
    scores = result.scores.sort("claim_id")
    assert scores["z"][0] == pytest.approx(0.6745 * -15 / 8, rel=1e-12)
    assert result.flag_rates.row(0, named=True) | {"rate": None} == {
        "segment": "UNKNOWN",
        "line": "UNKNOWN",
        "variable": "paid_flow",
        "values": 31,
        "flagged": 1,
        "status": "scored",
        "rate": None,
    }


def test_zero_mad_falls_back_to_the_mean_absolute_deviation() -> None:
    # 20 values of 5 and 11 of 6: median 5, MAD 0, mean |d| = 11/31
    result = _run(_payments([5.0] * 20 + [6.0] * 11))
    scored = result.scores.filter(pl.col("y") > 5.5)
    assert scored["z"][0] == pytest.approx(1 / (1.253314 * 11 / 31), rel=1e-12)
    assert result.flags.height == 0


def test_no_spread_flags_nothing() -> None:
    result = _run(_payments([5.0] * 31))
    assert result.flags.height == 0
    assert set(result.scores["z"].to_list()) == {0.0}


def test_small_groups_are_not_scored() -> None:
    result = _run(_payments(list(range(1, 30))))
    assert result.scores.height == 0
    assert result.flag_rates["status"].to_list() == ["too few values"]


def test_high_flag_rate_warns_of_mixed_populations() -> None:
    result = _run(_payments([5.0] * 28 + [1.0, 9.0, 9.5]), min_group_size=30)
    assert result.flags.height == 3
    assert len(result.warnings) == 1
    assert "may mix populations" in result.warnings[0]


def test_flows_follow_consecutive_rows_and_reserve_changes_are_scored() -> None:
    rows = [
        ("A", date(2024, 1, 31), 100.0, 50.0, "USD"),
        ("A", date(2024, 2, 29), 100.0, 0.0, "USD"),  # no payment; reserve to zero
        ("A", date(2024, 3, 31), 400.0, 0.0, "USD"),  # payment of 300; no reserve either side
        ("B", date(2024, 1, 31), 10.0, 0.0, "EUR"),  # no rate: not scored, counted
    ]
    result = robust_z_flags(_valuations(rows), None, {"USD": 30.0}, min_group_size=1)
    paid = result.scores.filter(pl.col("variable") == "paid_flow").sort("valuation_date")
    assert paid["amount"].to_list() == [3000.0, 9000.0]
    reserve = result.scores.filter(pl.col("variable") == "reserve_release")
    assert reserve["y"].to_list() == [pytest.approx(math.log(1 / 1501))]
    # the payment of 300 in March moves incurred from 100 to 400 (USD), 3000 to 12000 TRY
    incurred = result.scores.filter(pl.col("variable") == "incurred_change_at_payment")
    assert incurred.select("valuation_date", "before", "amount").rows() == [
        (date(2024, 3, 31), 3000.0, 12000.0)
    ]
    assert incurred["y"][0] == pytest.approx(math.log(12001 / 3001))
    assert result.not_converted == 1


def _reserves(kinds: dict[str, list[float]]) -> pl.DataFrame:
    """One claim per entry, valued monthly with the given case reserves (nothing paid)."""
    rows = [
        (claim, date(2024, month + 1, 28), 0.0, reserve, "TRY")
        for claim, reserves in kinds.items()
        for month, reserve in enumerate(reserves)
    ]
    return _valuations(rows)


def test_reserve_movements_are_split_into_moved_opened_and_released() -> None:
    result = robust_z_flags(
        _reserves(
            {
                "moved": [100.0, 150.0, 150.0],  # moves, then stays: the stay is no movement
                "opened": [0.0, 400.0],
                "released": [900.0, 0.0],
                "idle": [0.0, 0.0, 0.0],  # no reserve either side: nothing
            }
        ),
        None,
        {"TRY": 1.0},
        min_group_size=1,
        variables=("reserve_change", "reserve_opening", "reserve_release"),
    )
    got = {r["claim_id"]: (r["variable"], r["y"]) for r in result.scores.iter_rows(named=True)}
    assert got == {
        "moved": ("reserve_change", pytest.approx(math.log(151 / 101))),
        "opened": ("reserve_opening", pytest.approx(math.log(401))),
        "released": ("reserve_release", pytest.approx(math.log(1 / 901))),
    }


def test_each_kind_of_reserve_movement_has_its_own_scale() -> None:
    # 40 claims open a reserve of about 1000 and release it later: under one scale the
    # releases (about -7) sit far from the small moves (about 0.05) and are all flagged; under
    # one scale per kind the typical opening, release and move are normal and only the odd
    # claim (a reserve of 90 000 where 1000 is usual, opened and released) is flagged, and
    # not on its move, which is a normal 5 per cent.
    sizes = {f"C{k:02d}": 1000.0 * math.exp(0.02 * (k - 20)) for k in range(40)}
    reserves = {c: [0.0, size, size * 1.05, 0.0] for c, size in sizes.items()}
    reserves["BIG"] = [0.0, 90_000.0, 90_000.0 * 1.05, 0.0]
    result = robust_z_flags(_reserves(reserves), None, {"TRY": 1.0})
    flagged = result.flags.select("claim_id", "variable").rows()
    assert sorted(flagged) == [("BIG", "reserve_opening"), ("BIG", "reserve_release")]
    reasons = result.flags.sort("variable")["reason"].to_list()
    assert reasons[0].startswith("case reserve opened at 90000.0")
    assert reasons[1].startswith("case reserve of 94500.0 released")
    rates = result.flag_rates.filter(pl.col("variable").str.starts_with("reserve"))
    assert rates.select("variable", "values").sort("variable").rows() == [
        ("reserve_change", 41),
        ("reserve_opening", 41),
        ("reserve_release", 41),
    ]


def test_incurred_change_needs_a_payment_and_a_movement() -> None:
    rows = [
        ("A", date(2024, 1, 31), 0.0, 500.0, "TRY"),
        ("A", date(2024, 2, 29), 200.0, 300.0, "TRY"),  # paid from the reserve: incurred stays
        ("A", date(2024, 3, 31), 200.0, 900.0, "TRY"),  # reserve raised without a payment
        ("A", date(2024, 4, 30), 1700.0, 0.0, "TRY"),  # payment above the reserve: scored
        ("B", date(2024, 1, 31), 0.0, 100.0, "TRY"),
        ("B", date(2024, 2, 29), 50.0, 100.0, "EUR"),  # no rate on this row: counted
    ]
    result = robust_z_flags(
        _valuations(rows),
        None,
        {"TRY": 1.0},
        min_group_size=1,
        variables=("incurred_change_at_payment",),
    )
    assert result.scores.select("claim_id", "valuation_date", "y").rows() == [
        ("A", date(2024, 4, 30), pytest.approx(math.log(1701 / 1101)))
    ]
    assert result.not_converted == 1


def test_an_unforeseen_payment_is_flagged_where_its_size_alone_is_not() -> None:
    # 40 claims pay about 370 to 2600 out of a reserve up to 6 per cent above the payment;
    # one pays 3000 on a reserve of 100. Its payment sits inside the spread of payments, its
    # jump of incurred does not.
    rows = []
    for k in range(40):
        size = round(1000.0 * math.exp(0.05 * (k - 20)), 2)
        rows += [
            (f"C{k:02d}", date(2024, 1, 31), 0.0, size * (1 + 0.01 * (k % 7)), "TRY"),
            (f"C{k:02d}", date(2024, 2, 29), size, 0.0, "TRY"),
        ]
    rows += [
        ("X", date(2024, 1, 31), 0.0, 100.0, "TRY"),
        ("X", date(2024, 2, 29), 3000.0, 0.0, "TRY"),
    ]
    result = robust_z_flags(
        _valuations(rows),
        None,
        {"TRY": 1.0},
        variables=("paid_flow", "incurred_change_at_payment"),
    )
    flagged = result.flags.select("claim_id", "variable").rows()
    assert flagged == [("X", "incurred_change_at_payment")]
    assert result.flags["reason"][0].startswith(
        "incurred moved from 100.0 to 3000.0 with a payment"
    )


def test_groups_come_from_claims() -> None:
    valuations = _payments([*range(1, 31), 60])
    claims = pl.DataFrame(
        {
            "claim_id": valuations["claim_id"],
            "segment": ["NON_LIFE"] * 31,
            "line": ["MOTOR_OD"] * 31,
        }
    )
    result = robust_z_flags(valuations, claims, {"TRY": 1.0}, variables=("paid_flow",))
    assert result.flags.select("segment", "line").row(0) == ("NON_LIFE", "MOTOR_OD")


def test_unknown_variable_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown variables"):
        robust_z_flags(_payments([1.0]), None, {}, variables=("paid",))


# Ground truth (records 0043, 0060): recall of the injected extreme payments, at least 0.75 in
# MT08; a payment is recalled when its row is flagged on paid_flow or on the incurred change at
# the payment. Measured 2026-10-22 with MT08 1.1.0: 8 of 8 on baseline and on high_inflation
# (paid_flow alone 0 of 8), other flagged payment rows 15.1 and 14.1 per 1000 payments.
PAYMENT_VARIABLES = ("paid_flow", "incurred_change_at_payment")


@pytest.mark.slow
@pytest.mark.integration
@pytest.mark.parametrize("scenario", ["baseline", "high_inflation"])
def test_ground_truth_recall_of_injected_payment_outliers(scenario: str) -> None:
    if not medium(scenario).is_dir():
        pytest.skip(f"run `just synth {scenario} medium`")
    data = load_medium(scenario)
    result = robust_z_flags(data.valuations, data.claims, data.rates.rates)
    injected = data.faults.filter(pl.col("fault_type") == "extreme_payment_outliers").select(
        "claim_id", pl.col("date").alias("valuation_date")
    )
    keys = ["claim_id", "valuation_date"]
    paid = result.scores.filter(pl.col("variable") == "paid_flow")
    assert injected.join(paid, on=keys, how="semi").height == injected.height  # all scored
    flagged = (
        result.scores.filter(pl.col("variable").is_in(PAYMENT_VARIABLES) & pl.col("flagged"))
        .select(keys)
        .unique()
    )
    recall = injected.join(flagged, on=keys, how="semi").height / injected.height
    others = flagged.join(injected, on=keys, how="anti").height
    print(f"recall {recall:.2f}; other flagged payments per 1000 {1000 * others / paid.height:.2f}")
    assert recall >= 0.75


# Ground truth (record 0221): after MT08 1.2.0 no line has more than 10 per cent of its reserve
# movements flagged. Measured 2026-10-23: baseline and high_inflation medium 1.5 to 1.8 per
# cent per line (1.1.0: MOTOR_OD 45 per cent, PROPERTY 12 per cent).
MAX_RESERVE_SHARE = 0.10


@pytest.mark.slow
@pytest.mark.integration
@pytest.mark.parametrize("scenario", ["baseline", "high_inflation"])
def test_ground_truth_reserve_movements_are_not_mostly_flagged(scenario: str) -> None:
    if not medium(scenario).is_dir():
        pytest.skip(f"run `just synth {scenario} medium`")
    data = load_medium(scenario)
    result = robust_z_flags(data.valuations, data.claims, data.rates.rates)
    shares = reserve_flag_shares(result)
    print({line: round(share, 4) for line, share in shares.items()})
    assert set(shares) >= {"MOTOR_OD", "MOTOR_TPL", "PROPERTY"}
    assert max(shares.values()) <= MAX_RESERVE_SHARE
    assert result.warnings == ()  # no group above the 5 per cent that suggests mixed populations
