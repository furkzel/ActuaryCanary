"""The four suggested causes of a material gap (CV12, record 0424), each on hand data."""

from datetime import date

from actuarycanary.ledger import causes

JUN, JUL, AUG = date(2023, 6, 30), date(2023, 7, 31), date(2023, 8, 31)


def test_a_gap_offset_by_the_opposite_gap_of_the_next_month_is_cut_off_timing() -> None:
    gaps = {JUN: 840.0, JUL: -836.0, AUG: 0.0}
    found = causes.cut_off_timing(JUN, gaps)
    assert found is not None and found.code == causes.CUT_OFF_TIMING
    assert "2023-07" in found.evidence and "-836" in found.evidence
    again = causes.cut_off_timing(JUL, gaps)  # the month after sees the month before
    assert again is not None and "2023-06" in again.evidence


def test_cut_off_timing_needs_an_opposite_gap_of_about_the_same_size() -> None:
    assert causes.cut_off_timing(JUN, {JUN: 840.0, JUL: 830.0}) is None  # same sign
    assert causes.cut_off_timing(JUN, {JUN: 840.0, JUL: -500.0}) is None  # not the same size
    assert causes.cut_off_timing(JUN, {JUN: 840.0}) is None  # no neighbour
    assert causes.cut_off_timing(JUN, {JUN: 840.0, AUG: -840.0}) is None  # not the month after
    assert causes.cut_off_timing(JUN, {JUN: 100.0, JUL: -95.0}) is not None  # exactly 5 per cent
    assert causes.cut_off_timing(JUN, {JUN: 100.0, JUL: -94.9}) is None


def test_a_gap_within_five_per_cent_of_the_foreign_part_is_a_currency_difference() -> None:
    found = causes.currency(-1511.0, 44898.0)
    assert found is not None and found.code == causes.CURRENCY and "3.4%" in found.evidence
    assert causes.currency(2500.0, 44898.0) is None  # more than a rate can explain
    assert causes.currency(-10.0, 0.0) is None  # no foreign-currency row
    assert causes.currency(-10.0, None) is None  # the class cannot tell


def test_a_loading_that_stays_the_same_for_three_months_is_ibnr_in_the_outstanding() -> None:
    steady = {date(2024, m, 28): 0.08 for m in (5, 6, 7)}
    found = causes.ibnr_in_outstanding("OUTSTANDING", date(2024, 6, 28), steady)
    assert found is not None and found.code == causes.IBNR_IN_OUTSTANDING
    assert "8.0%" in found.evidence and "3 months" in found.evidence
    assert causes.ibnr_in_outstanding("PREMIUM", date(2024, 6, 28), steady) is None
    assert (
        causes.ibnr_in_outstanding(
            "OUTSTANDING", date(2024, 6, 28), {**steady, date(2024, 7, 28): 0.2}
        )
        is None
    )
    two = dict(list(steady.items())[:2])
    assert causes.ibnr_in_outstanding("OUTSTANDING", date(2024, 5, 28), two) is None
    assert causes.ibnr_in_outstanding("OUTSTANDING", date(2024, 9, 28), steady) is None


def test_an_unmapped_balance_of_the_size_of_the_gap_is_a_suggestion() -> None:
    found = causes.unmapped_account(-18000.0, 18416.0, ["297"])
    assert found is not None and found.code == causes.UNMAPPED_ACCOUNT and "297" in found.evidence
    assert causes.unmapped_account(-840000.0, 18416.0, ["297"]) is None
    assert causes.unmapped_account(-18000.0, 0.0, []) is None
    assert causes.unmapped_account(18000.0, 18416.0, ["297"]) is not None  # the sign is not asked
