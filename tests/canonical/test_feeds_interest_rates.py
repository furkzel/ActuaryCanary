"""Row rules of the interest_rates feed that decide which points can enter a curve (DV-IRT-01 to
-07 and -10), and the checks DV-IRT-08 and -09 of the quality report."""

from datetime import date
from typing import Any

from actuarycanary.canonical.feeds import UNMAPPED, CanonicalFeed, canonicalise
from actuarycanary.convert.discount import DiscountSettings, resolve_discount
from actuarycanary.methods.assumptions import AssumptionsRegister
from actuarycanary.quality.checks import CHECKS, Context
from actuarycanary.spec.loader import load_specs
from tests.canonical.test_feeds import _rules, _table

SPECS = load_specs()
DAY = date(2025, 12, 31)


def point(months: Any = 12, rate: Any = 0.10, **values: Any) -> dict[str, Any]:
    row = {
        "curve_id": "C",
        "date": DAY,
        "tenor_months": months,
        "rate": rate,
        "rate_type": "SPOT",
        "compounding": "ANNUAL",
        "currency": "TRY",
        "source": "TEST",
    }
    return row | values


def feed(rows: list[dict[str, Any]]) -> CanonicalFeed:
    return canonicalise(_table(rows, "interest_rates"), SPECS.data["interest_rates"])


def test_a_clean_curve_passes_every_rule() -> None:
    clean = feed([point(12), point(24, 0.11), point(36, 0.12)])
    assert clean.frame.height == 3 and clean.findings == ()
    assert clean.frame["tenor_months"].dtype.is_integer()


def test_dv_irt_01_rows_without_a_key_or_a_value_are_excluded() -> None:
    found = feed([point(12), point(None), point(24, None), point(36, curve_id=None)])
    assert found.frame["tenor_months"].to_list() == [12]
    assert _rules(found) == {"DV-IRT-01": 3}


def test_dv_irt_02_unmapped_rate_types_and_compoundings_are_excluded() -> None:
    found = feed(
        [
            point(12),
            point(24, rate_type=UNMAPPED),
            point(36, compounding=UNMAPPED),
            point(48, compounding=None),  # an empty compounding means ANNUAL
        ]
    )
    assert found.frame["tenor_months"].to_list() == [12, 48]
    assert found.frame["compounding"].to_list() == ["ANNUAL", "ANNUAL"]
    assert _rules(found) == {"DV-IRT-02": 2}


def test_dv_irt_03_a_tenor_must_be_a_positive_whole_number() -> None:
    found = feed([point(12), point(0), point(-12), point(7.5)])
    assert found.frame["tenor_months"].to_list() == [12]
    assert _rules(found) == {"DV-IRT-03": 3}


def test_dv_irt_04_a_rate_in_per_cent_is_excluded_and_the_finding_says_so() -> None:
    found = feed([point(12, 0.25), point(24, 25.0), point(36, -0.10)])
    assert found.frame["rate"].to_list() == [0.25]
    assert _rules(found) == {"DV-IRT-04": 2}
    assert "per cent" in next(f.message for f in found.findings if f.rule == "DV-IRT-04")


def test_dv_irt_05_invalid_codes_and_a_second_currency_of_a_curve_are_excluded() -> None:
    found = feed(
        [
            point(12),
            point(24),
            point(36, currency="EUR"),  # a second currency in the curve: the majority wins
            point(48, currency="euro"),  # not an ISO code
        ]
    )
    assert found.frame["tenor_months"].to_list() == [12, 24]
    assert _rules(found) == {"DV-IRT-05": 2}


def test_dv_irt_06_of_two_rates_for_one_point_the_later_row_is_kept() -> None:
    found = feed([point(12, 0.10), point(24, 0.11), point(12, 0.12), point(12, 0.12)])
    assert sorted(found.frame["rate"].to_list()) == [0.11, 0.12]
    assert _rules(found) == {"DV-IRT-06": 2}


def test_dv_irt_07_a_curve_on_a_date_with_two_rate_types_is_excluded_whole() -> None:
    found = feed(
        [
            point(12),
            point(24, rate_type="PAR"),
            point(12, curve_id="D"),
            point(12, curve_id="C", date=date(2025, 11, 30)),
        ]
    )
    assert sorted(found.frame["curve_id"].to_list()) == ["C", "D"]
    assert found.frame.filter(found.frame["date"] == DAY).height == 1
    assert _rules(found) == {"DV-IRT-07": 2}


def test_dv_irt_10_par_and_forward_rows_need_whole_year_tenors() -> None:
    found = feed(
        [
            point(12, rate_type="PAR"),
            point(18, rate_type="PAR"),
            point(18, rate_type="FORWARD", curve_id="D"),
            point(18, rate_type="SPOT", curve_id="E"),
        ]
    )
    assert sorted(found.frame["curve_id"].to_list()) == ["C", "E"]
    assert _rules(found) == {"DV-IRT-10": 2}


def _context(rows: list[dict[str, Any]], **settings: Any) -> Context:
    frame = feed(rows).frame
    discount = resolve_discount(
        DiscountSettings(**settings), AssumptionsRegister(), frame, DAY, "TRY"
    )
    return Context({"interest_rates": frame}, SPECS.data, DAY, "TRY", discount=discount)


def test_the_curve_rules_are_not_evaluated_without_a_named_curve() -> None:
    context = _context([point(12)])
    assert CHECKS["DV-IRT-08"](context) is None and CHECKS["DV-IRT-09"](context) is None
    assert CHECKS["DV-IRT-08"](Context({}, SPECS.data, DAY)) is None


def test_dv_irt_08_passes_for_a_current_curve_and_fails_for_an_old_or_missing_one() -> None:
    current = CHECKS["DV-IRT-08"](_context([point(12)], curve_id="C"))
    assert current is not None and (current.checked, current.failed) == (1, 0)
    old = CHECKS["DV-IRT-08"](_context([point(12, date=date(2025, 6, 30))], curve_id="C"))
    assert old is not None and old.failed == 1 and "days older" in old.message
    late = CHECKS["DV-IRT-08"](_context([point(12, date=date(2026, 6, 30))], curve_id="C"))
    assert late is not None and late.failed == 1 and "DV-IRT-08" in late.message


def test_dv_irt_09_lists_a_jump_between_tenors_as_information() -> None:
    steady = CHECKS["DV-IRT-09"](_context([point(12), point(24), point(36)], curve_id="C"))
    assert steady is not None and steady.failed == 0
    jumpy = CHECKS["DV-IRT-09"](
        _context([point(12, 0.05), point(24, 0.05), point(36, 0.60)], curve_id="C")
    )
    assert jumpy is not None and jumpy.failed == 1
