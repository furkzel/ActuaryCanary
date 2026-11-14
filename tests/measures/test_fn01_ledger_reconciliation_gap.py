"""FN01 (CV12): the platform's figure minus the mapped ledger amount, with materiality."""

from datetime import date
from typing import Any

import polars as pl
import pytest

from actuarycanary.ledger.profile import (
    AccountProfile,
    AccountRule,
    ProfileInUse,
    chart_fingerprint,
)
from actuarycanary.ledger.settings import LedgerSettings
from actuarycanary.measures.ledger_measures import RUN_KEY, LedgerRun, gap_table
from actuarycanary.measures.ledger_platform import LINKS, Side
from actuarycanary.measures.model import MeasureInputs
from tests.measures.helpers import make_inputs, measure
from tests.quality.builders import balance, expense, policy, premium

JAN, FEB, MAR = date(2024, 1, 31), date(2024, 2, 29), date(2024, 3, 31)


def rule(pattern: str, account_class: Any, sign: Any) -> AccountRule:
    return AccountRule(
        pattern=pattern, account_class=account_class, sign=sign, balance_kind="PERIOD"
    )


def run_with(settings: LedgerSettings | None = None, *rules: AccountRule) -> LedgerRun:
    codes = [r.pattern for r in rules]
    profile = AccountProfile(
        fingerprint=chart_fingerprint(codes), accounts=codes, rules=list(rules)
    )
    return LedgerRun(ProfileInUse(profile, "0" * 64, None, False), settings or LedgerSettings())


def ledger(code: str, values: list[float], entity: str = "E") -> list[dict]:
    return [
        balance(m, entity=entity, account=code, closing_balance=v)
        for m, v in enumerate(values, start=1)
    ]


def inputs_for(rows: dict, settings: LedgerSettings | None = None, **extra) -> MeasureInputs:
    inputs = make_inputs(rows, cut_off=MAR, **extra)
    inputs.cache[RUN_KEY] = run_with(
        settings,
        rule("600", "PREMIUM", -1),
        rule("770", "EXPENSE", 1),
        rule("660", "INVESTMENT", -1),
    )
    return inputs


def feeds(premiums: list[float]) -> dict[str, list[dict]]:
    return {
        "policies": [policy(entity="E")],
        "premiums": [
            premium(transaction_id=f"T{i}", booking_date=date(2024, i, 5), amount=v)
            for i, v in enumerate(premiums, start=1)
        ],
        "expenses": [expense(period=d, amount=50.0, entity="E") for d in (JAN, FEB, MAR)],
    }


def gaps(result) -> dict[tuple[str, str], dict]:
    assert result.frame is not None, result.reason
    return {
        (r["account_class"], r["calendar_period"]): r for r in result.frame.iter_rows(named=True)
    }


def test_a_premium_gap_of_four_is_not_material_and_one_of_six_is() -> None:
    rows = {
        **feeds([1004.0, 1000.0, 1006.0]),
        "ledger": ledger("600", [-1000.0] * 3) + ledger("770", [50.0] * 3),
    }
    result = measure(inputs_for(rows), "FN01", "entity", "account_class", "calendar_period")
    found = gaps(result)
    jan, mar = found[("PREMIUM", "2024-01")], found[("PREMIUM", "2024-03")]
    assert (jan["platform_amount"], jan["ledger_amount"], jan["gap"]) == (1004.0, 1000.0, 4.0)
    assert jan["share"] == pytest.approx(0.004) and not jan["material"]  # 0.4 per cent
    assert mar["gap"] == 6.0 and mar["share"] == pytest.approx(0.006) and mar["material"]
    assert found[("PREMIUM", "2024-02")]["gap"] == 0.0
    assert all(found[("EXPENSE", m)]["gap"] == 0.0 for m in ("2024-01", "2024-02", "2024-03"))
    assert result.frame is not None and result.frame["entity"].unique().to_list() == ["E"]


def test_a_class_whose_feed_is_not_loaded_is_not_reconciled_never_a_gap() -> None:
    rows = {
        "expenses": feeds([])["expenses"],
        "ledger": ledger("600", [-1000.0] * 3) + ledger("770", [50.0] * 3),
    }
    result = measure(inputs_for(rows), "FN01", "entity", "account_class", "calendar_period")
    found = gaps(result)
    assert {c for c, _ in found} == {"EXPENSE"}
    reasons = dict(result.tables["not_reconciled"].iter_rows())
    assert "premiums" in reasons["PREMIUM"] and "not loaded" in reasons["PREMIUM"]
    assert any("PREMIUM not reconciled" in n for n in result.notes)


def test_investment_and_other_are_mapped_and_deliberately_not_reconciled() -> None:
    rows = {
        **feeds([1000.0] * 3),
        "ledger": ledger("600", [-1000.0] * 3) + ledger("660", [-7.0] * 3),
    }
    result = measure(inputs_for(rows), "FN01", "entity", "account_class", "calendar_period")
    assert "INVESTMENT" not in {c for c, _ in gaps(result)}
    reasons = dict(result.tables["not_reconciled"].iter_rows())
    assert "deliberately" in reasons["INVESTMENT"]


def test_a_foreign_currency_month_is_converted_at_the_rate_of_the_booking_date() -> None:
    usd = premium(transaction_id="U", booking_date=date(2024, 2, 5), amount=100.0, currency="USD")
    rows = {
        "policies": [policy(entity="E")],
        "premiums": [premium(amount=1000.0), usd],
        "ledger": ledger("600", [-1000.0, -3000.0, 0.0]),
    }
    market = [("USD/TRY", "FX_SPOT", date(2024, 2, 5), 30.0)]
    result = measure(
        inputs_for(rows, market_rows=market), "FN01", "entity", "account_class", "calendar_period"
    )
    found = gaps(result)
    assert found[("PREMIUM", "2024-02")]["platform_amount"] == 3000.0
    assert found[("PREMIUM", "2024-02")]["gap"] == 0.0
    # the ledger booked the same dollars at 29: the gap is the rate difference
    rows["ledger"] = ledger("600", [-1000.0, -2900.0, 0.0])
    result = measure(
        inputs_for(rows, market_rows=market), "FN01", "entity", "account_class", "calendar_period"
    )
    assert gaps(result)[("PREMIUM", "2024-02")]["gap"] == 100.0


def test_a_month_the_ledger_lacks_is_not_computed() -> None:
    rows = {**feeds([1000.0] * 3), "ledger": ledger("600", [-1000.0, -1000.0, -1000.0])}
    rows["ledger"] = [r for r in rows["ledger"] if r["period"] != FEB]
    found = gaps(measure(inputs_for(rows), "FN01", "entity", "account_class", "calendar_period"))
    assert ("PREMIUM", "2024-02") not in found and ("PREMIUM", "2024-03") in found


def test_a_request_with_a_line_split_is_refused_with_the_reason() -> None:
    rows = {**feeds([1000.0] * 3), "ledger": ledger("600", [-1000.0] * 3)}
    result = measure(inputs_for(rows), "FN01", "entity", "line")
    assert result.frame is None and "not built" in result.reason


# --- materiality and the zero ledger, on the table itself --------------------------------------


def table(ledger_amount: float, platform_amount: float, settings: LedgerSettings):
    amounts = pl.DataFrame(
        {
            "entity": ["E"],
            "account_class": ["PREMIUM"],
            "period": [JAN],
            "ledger_amount": [ledger_amount],
        }
    )
    months = amounts.select("entity", "period")
    side = Side(pl.DataFrame({"entity": ["E"], "period": [JAN], "amount": [platform_amount]}))
    out, _ = gap_table(amounts, months, {"PREMIUM": side}, settings)
    return out.row(0, named=True)


@pytest.mark.parametrize(
    ("platform", "material"), [(150.0, False), (150.01, True), (50.0, False), (49.99, True)]
)
def test_the_ratio_boundary_is_a_gap_larger_than_the_ratio_times_the_ledger(
    platform: float, material: bool
) -> None:
    assert table(100.0, platform, LedgerSettings(materiality_ratio=0.5))["material"] is material


@pytest.mark.parametrize(("platform", "material"), [(110.0, False), (110.01, True)])
def test_the_amount_boundary_is_a_gap_larger_than_the_amount(
    platform: float, material: bool
) -> None:
    settings = LedgerSettings(materiality_ratio=0.0, materiality_amount=10.0)
    assert table(100.0, platform, settings)["material"] is material


def test_both_thresholds_must_be_exceeded() -> None:
    settings = LedgerSettings(materiality_ratio=0.5, materiality_amount=100.0)
    assert not table(100.0, 180.0, settings)["material"]  # above the ratio, below the amount
    assert not table(1000.0, 1200.0, settings)["material"]  # above the amount, below the ratio
    assert table(1000.0, 1600.0, settings)["material"]


def test_a_ledger_amount_of_zero_has_a_gap_and_no_share() -> None:
    row = table(0.0, 5.0, LedgerSettings())
    assert row["gap"] == 5.0 and row["share"] is None and row["material"]
    assert "zero" in row["note"]


def test_every_reconciled_class_has_a_link_that_names_its_feeds() -> None:
    from actuarycanary.ledger.classes import RECONCILED_CLASSES

    assert tuple(LINKS) == RECONCILED_CLASSES
    assert all(
        link.needs and link.measure and link.kind in ("flow", "stock") for link in LINKS.values()
    )
    assert {c for c, link in LINKS.items() if link.kind == "stock"} == {"OUTSTANDING", "UPR"}
    assert LINKS["RI"].basis == "CEDED" and {k.basis for c, k in LINKS.items() if c != "RI"} == {
        "GROSS"
    }
