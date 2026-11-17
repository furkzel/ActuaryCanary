"""The checks of the life feeds (record 0442): one passing and one failing hand case per rule, the
rules about two feeds without the second, and the generated life book, which passes every rule
(the generator injects no fault into the life feeds)."""

from datetime import date
from typing import Any

import polars as pl
import pytest

from actuarycanary.canonical.life import AGE_HIGH, AGE_LOW, parse_age_band
from actuarycanary.quality.checks import CANONICAL_RULES, Context
from actuarycanary.quality.checks_life import LIFE_CHECKS, NEEDS
from actuarycanary.synthetic.check import check_folder
from tests.quality.builders import SPECS, Rows, frames

LIFE = ("life_in_force", "life_events", "fund_flows")
CUT_OFF = date(2024, 12, 31)


def lif(contract: str = "L1", year: int = 2022, **values: Any) -> dict[str, Any]:
    base = {
        "contract_id": contract,
        "valuation_date": date(year, 12, 31),
        "product": "TERM",
        "entry_date": date(2020, 6, 1),
        "age_band": str(40 + year - 2020),
        "status": "IN_FORCE",
    }
    return {**base, **values}


def lev(event: str, contract: str = "L1", day: date = date(2023, 5, 1), **values: Any):
    return {
        "event_id": f"E{event}{contract}{day}",
        "contract_id": contract,
        "event_date": day,
        "event_type": event,
        **values,
    }


def ffl(kind: str, amount: float, day: date = date(2023, 5, 1), **values: Any):
    return {
        "flow_id": f"F{kind}{amount}{day}{values.get('fund_code', '')}",
        "contract_id": "L1",
        "flow_date": day,
        "amount": amount,
        "currency": "TRY",
        "flow_type": kind,
        **values,
    }


def _frames(rows: Rows) -> dict[str, pl.DataFrame]:
    built = frames(rows)
    if "life_in_force" in built:
        low, high, _ = parse_age_band(pl.col("age_band"))
        built["life_in_force"] = built["life_in_force"].with_columns(
            low.alias(AGE_LOW), high.alias(AGE_HIGH)
        )
    return built


def _run(rule: str, rows: Rows, cut_off: date | None = CUT_OFF):
    return LIFE_CHECKS[rule](Context(_frames(rows), SPECS, cut_off))


BOOK = [lif(year=y) for y in (2022, 2023, 2024)]

# rule -> (rows that pass, rows that fail, checked and failed in the failing rows)
CASES: dict[str, tuple[Rows, Rows, int, int]] = {
    "DV-LIF-06": (
        {"life_in_force": BOOK},
        {"life_in_force": [*BOOK[:2], lif(year=2024, product="OTHER"), lif("L2")]},
        2,
        1,
    ),
    "DV-LIF-07": (
        {
            "life_in_force": [
                *BOOK,
                lif("L2", 2022, age_band="40-44"),
                lif("L2", 2023, age_band="45-49"),  # a band moves by its width
                lif("L3", 2023, age_band="85+"),
                lif("L3", 2024, age_band="85+"),
            ]
        },
        {"life_in_force": [*BOOK[:2], lif(year=2024, age_band="50"), lif("L2")]},
        1,
        1,
    ),
    "DV-LIF-08": (
        {
            "life_in_force": [
                *BOOK[:1],
                lif(year=2023, status="LAPSED"),
                lif(year=2024),
                lif("L2", 2023, status="DEATH_CLAIM"),
            ],
            "life_events": [lev("REINSTATEMENT", day=date(2024, 3, 1))],
        },
        {"life_in_force": [*BOOK[:1], lif(year=2023, status="LAPSED"), lif(year=2024), lif("L2")]},
        2,
        1,
    ),
    "DV-LIF-09": (
        {"life_in_force": [lif(sum_assured=0.0, fund_value=5.0, term_years=10.0)]},
        {"life_in_force": [lif(sum_assured=-1.0), lif("L2", annual_premium=3.0)]},
        2,
        1,
    ),
    "DV-LIF-10": (
        {
            "life_in_force": [
                *BOOK,
                lif("L2", 2022),
                lif("L2", 2023, status="LAPSED"),  # left: no row expected in 2024
            ]
        },
        {"life_in_force": [BOOK[0], BOOK[2], *(lif("L2", y) for y in (2022, 2023, 2024))]},
        2,
        1,
    ),
    "DV-LEV-04": (
        {"life_events": [lev("DEATH")], "life_in_force": BOOK},
        {"life_events": [lev("DEATH"), lev("DEATH", "L9")], "life_in_force": BOOK},
        2,
        1,
    ),
    "DV-LEV-05": (
        {"life_events": [lev("DEATH")], "life_in_force": BOOK},
        {
            "life_events": [
                lev("DEATH"),
                lev("LAPSE", day=date(2019, 1, 1)),
                lev("LAPSE", day=date(2025, 1, 1)),
            ],
            "life_in_force": BOOK,
        },
        3,
        2,
    ),
    "DV-LEV-06": (
        {
            "life_events": [
                lev("LAPSE", day=date(2022, 3, 1)),
                lev("REINSTATEMENT", day=date(2022, 9, 1)),
                lev("DEATH"),
            ]
        },
        {"life_events": [lev("LAPSE", day=date(2022, 3, 1)), lev("DEATH")]},
        2,
        1,
    ),
    "DV-LEV-07": (
        {
            "life_events": [
                lev("DEATH", day=date(2023, 12, 1), report_date=date(2024, 2, 1)),
                lev("LAPSE", "L2", day=date(2022, 2, 1)),
                lev("REINSTATEMENT", "L2", day=date(2022, 6, 1)),
            ],
            # the death is known after the 2023 valuation: the 2024 status is compared
            "life_in_force": [
                *BOOK[:2],
                lif(year=2024, status="DEATH_CLAIM"),
                lif("L2", 2022),
            ],
        },
        {
            "life_events": [lev("DEATH"), lev("LAPSE", "L2")],
            "life_in_force": [*BOOK, lif("L2", 2023, status="SURRENDERED")],
        },
        2,
        2,
    ),
    "DV-LEV-08": (
        {"life_events": [lev("DEATH", report_date=date(2023, 6, 1)), lev("LAPSE", "L2")]},
        {"life_events": [lev("DEATH", report_date=date(2023, 4, 1))]},
        1,
        1,
    ),
    "DV-LEV-09": (
        {"life_events": [lev("DEATH", amount=0.0)]},
        {"life_events": [lev("DEATH", amount=-5.0), lev("SURRENDER", "L2", amount=5.0)]},
        2,
        1,
    ),
    "DV-FFL-05": (
        {"fund_flows": [ffl("CONTRIBUTION", 10.0)], "life_in_force": BOOK},
        {
            "fund_flows": [ffl("CONTRIBUTION", 10.0), ffl("FEE", 1.0, contract_id="L9")],
            "life_in_force": BOOK,
        },
        2,
        1,
    ),
    "DV-FFL-06": (
        {
            "fund_flows": [
                ffl("FUND_SWITCH", -40.0, fund_code="A"),
                ffl("FUND_SWITCH", 40.0, fund_code="B"),
            ]
        },
        {
            "fund_flows": [
                ffl("FUND_SWITCH", -40.0, fund_code="A"),
                ffl("FUND_SWITCH", 39.0, fund_code="B"),
                ffl("FUND_SWITCH", -5.0, date(2023, 6, 1), fund_code="A"),
                ffl("FUND_SWITCH", 5.0, date(2023, 6, 1)),
                ffl("FUND_SWITCH", -7.0, date(2023, 7, 1), fund_code="A"),
                ffl("FUND_SWITCH", 7.0, date(2023, 7, 1), fund_code="C"),
            ]
        },
        3,
        2,
    ),
    "DV-FFL-07": (
        {"fund_flows": [ffl("CONTRIBUTION", 10.0), ffl("FUND_SWITCH", -40.0, fund_code="A")]},
        {"fund_flows": [ffl("CONTRIBUTION", -10.0), ffl("FEE", 0.0), ffl("FEE", 2.0)]},
        3,
        2,
    ),
    "DV-FFL-08": (
        {
            "fund_flows": [
                ffl("CONTRIBUTION", 10.0, date(2022, 1, 1)),
                ffl("CONTRIBUTION", 10.0, date(2022, 9, 1)),
            ],
            "life_events": [
                lev("LAPSE", day=date(2022, 3, 1)),
                lev("REINSTATEMENT", day=date(2022, 6, 1)),
            ],
        },
        {
            "fund_flows": [
                ffl("CONTRIBUTION", 10.0, date(2022, 1, 1)),
                ffl("CONTRIBUTION", 10.0, date(2022, 9, 1)),
                ffl("FEE", 1.0, date(2022, 9, 1)),
            ],
            "life_events": [lev("LAPSE", day=date(2022, 3, 1))],
        },
        2,
        1,
    ),
}


def test_every_life_rule_is_checked_or_applied_by_the_canonical_step() -> None:
    rules = {r.id for c in LIFE for r in SPECS[c].validation}
    assert len(rules) == 27
    canonical = {r for c in LIFE for r in CANONICAL_RULES[c]}
    assert canonical | set(LIFE_CHECKS) == rules and not canonical & set(LIFE_CHECKS)
    assert set(CASES) == set(LIFE_CHECKS)


@pytest.mark.parametrize("rule", sorted(CASES))
def test_passing_rows_have_no_failure(rule: str) -> None:
    outcome = _run(rule, CASES[rule][0])
    assert outcome is not None and outcome.checked > 0
    assert outcome.failed == 0 and outcome.refs == ()


@pytest.mark.parametrize("rule", sorted(CASES))
def test_failing_rows_are_counted_with_source_rows(rule: str) -> None:
    _, rows, checked, failed = CASES[rule]
    outcome = _run(rule, rows)
    assert outcome is not None
    assert (outcome.checked, outcome.failed) == (checked, failed)
    assert 0 < len(outcome.refs) <= max(failed, 5) and all(r.file == "f.xlsx" for r in outcome.refs)
    owner = next(c for c in LIFE if any(r.id == rule for r in SPECS[c].validation))
    assert outcome.concept == owner


@pytest.mark.parametrize("rule", sorted(NEEDS))
def test_a_rule_about_two_feeds_is_not_evaluated_without_the_second(rule: str) -> None:
    owner = next(c for c in LIFE if any(r.id == rule for r in SPECS[c].validation))
    assert _run(rule, {owner: CASES[rule][1][owner]}) is None


def test_dv_lev_05_without_a_cut_off_checks_the_entry_date_only() -> None:
    rows = CASES["DV-LEV-05"][1]
    outcome = _run("DV-LEV-05", rows, cut_off=None)
    assert outcome is not None and outcome.failed == 1


# --- the generated life book ----------------------------------------------------------------


@pytest.fixture(scope="module", params=["life_book", "messy_headers"])
def life_report(request, scenario_checked):
    return request.param, scenario_checked(request.param)[1]


def test_the_generated_life_book_passes_every_life_rule(life_report) -> None:
    """The generator writes the life feeds without faults (check_phase2.py, the scenarios):
    every rule is evaluated on rows and none fails."""
    scenario, report = life_report
    used = {s.rule for s in report.rules if s.concept in LIFE}
    expected = {r.id for c in LIFE for r in SPECS[c].validation}
    assert used >= expected, (scenario, expected - used)
    assert [f.rule for f in report.findings if f.concept in LIFE] == [], scenario
    assert not [r for r, _ in report.not_evaluated if r.startswith(("DV-LIF", "DV-LEV", "DV-FFL"))]
    # "What was loaded" of the data quality appendix: rows and the period of each life feed
    loaded = {c.concept: c for c in report.coverage if c.concept in LIFE}
    assert all(c.loaded and c.rows > 0 and c.first and c.last for c in loaded.values())
    assert loaded["life_in_force"].last == date(2025, 12, 31)


def test_the_checker_of_the_generator_finds_no_life_fault(scenario_folder) -> None:
    rules = ("DV-LIF", "DV-LEV", "DV-FFL")
    found = [v for v in check_folder(scenario_folder("life_book"), later_feeds=True)]
    assert [(v.rule, v.count) for v in found if v.rule.startswith(rules) and v.count] == []
