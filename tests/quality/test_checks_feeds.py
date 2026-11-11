"""The checks of the four feeds built by F1bc (DV-RTY, DV-RTR, DV-RCV, DV-LDG): one set of
frames that passes and one that fails for every rule, built in code, and the wiring of one rule
of each feed through the quality engine."""

from datetime import date
from typing import Any

import pytest

from actuarycanary.canonical.feeds import CanonicalFeed
from actuarycanary.quality.checks import Context
from actuarycanary.quality.checks_feeds import FEED_CHECKS, NEEDS, NOT_BUILT
from actuarycanary.quality.engine import evaluate
from actuarycanary.spec.loader import load_specs
from tests.quality.builders import (
    SPECS,
    Rows,
    balance,
    claim,
    cv,
    frames,
    movement,
    policy,
    premium,
    recovery,
    series,
    treaty,
)

CATALOGUE = load_specs()
XL = {"treaty_type": "EXCESS_OF_LOSS", "cession_share": None}
PAID = {"type": "CEDED_CLAIM_PAID", "claim_id": "1"}
HELD = {"type": "CEDED_CASE_RESERVE", "claim_id": "1"}
CEDED = {"type": "CEDED_PREMIUM", "policy_id": "P1"}
FULL: dict[str, Any] = {"opening_balance": 4.0, "debit": 7.0, "credit": 1.0}

# rule -> (frames that pass, frames that fail, checked in the failing frames, failing)
CASES: dict[str, tuple[Rows, Rows, int, int]] = {
    "DV-RTY-04": (
        {"reinsurance_treaties": [treaty()]},
        {"reinsurance_treaties": [treaty(), treaty(treaty_id="B", currency="LIRA")]},
        2,
        1,
    ),
    "DV-RTY-05": (
        {"reinsurance_treaties": [treaty(), treaty(treaty_id="XL", retention=5.0, **XL)]},
        {
            "reinsurance_treaties": [
                treaty(cession_share=None),
                treaty(treaty_id="XL", retention=None, **XL),
                treaty(treaty_id="S", treaty_type="SURPLUS", retention=5.0, number_of_lines=None),
                treaty(treaty_id="F", treaty_type="FACULTATIVE", cession_share=None),
            ]
        },
        4,
        3,
    ),
    "DV-RTY-06": (
        {"reinsurance_treaties": [treaty(placed_share=1.0, ceding_commission=0.0)]},
        {"reinsurance_treaties": [treaty(cession_share=1.2), treaty(placed_share=-0.1), treaty()]},
        3,
        2,
    ),
    "DV-RTY-07": (
        {"reinsurance_treaties": [treaty(retention=0.0, limit=5.0, number_of_lines=1.0)]},
        {
            "reinsurance_treaties": [
                treaty(retention=-1.0),
                treaty(number_of_lines=0.0),
                treaty(reinstatements=-1.0),
                treaty(limit=0.0),
            ]
        },
        4,
        3,
    ),
    "DV-RTY-09": (
        {
            "reinsurance_treaties": [
                treaty(),
                treaty(inception_date=date(2025, 1, 1), expiry_date=date(2026, 1, 1)),
                treaty(treaty_id="QS2", line="Y"),
                treaty(treaty_id="L1", retention=10.0, limit=40.0, **XL),
                treaty(treaty_id="L2", retention=50.0, limit=50.0, **XL),
            ]
        },
        {
            "reinsurance_treaties": [
                treaty(),
                treaty(treaty_id="QS2", inception_date=date(2024, 7, 1)),
                treaty(treaty_id="L1", retention=10.0, limit=40.0, **XL),
                treaty(treaty_id="L2", retention=49.0, limit=None, **XL),
                treaty(treaty_id="L3", retention=10.0, limit=40.0, loss_basis="EVENT", **XL),
            ]
        },
        5,
        4,
    ),
    "DV-RTY-10": (
        {
            "reinsurance_treaties": [treaty(index_series="CPI"), treaty(treaty_id="B")],
            "market": [series(series_id="CPI", kind="PRICE_INDEX")],
        },
        {
            "reinsurance_treaties": [treaty(index_series="CPI"), treaty(index_series="USD")],
            "market": [series(series_id="CPI", kind="PRICE_INDEX"), series()],
        },
        2,
        1,
    ),
    "DV-RTR-05": (
        {"reinsurance_transactions": [movement()], "reinsurance_treaties": [treaty()]},
        {
            "reinsurance_transactions": [movement(), movement(treaty_id="ZZ")],
            "reinsurance_treaties": [treaty()],
        },
        2,
        1,
    ),
    "DV-RTR-06": (
        {
            "reinsurance_transactions": [movement(), movement(**PAID)],
            "reinsurance_treaties": [treaty()],
            "claims": [claim()],
        },
        {
            "reinsurance_transactions": [
                movement(**PAID),  # loss on 2024-01-10, covered
                movement(claim_id="2", type="CEDED_CLAIM_PAID"),  # loss in 2023, not covered
                movement(booking_date=date(2023, 12, 31)),  # premium before the inception
                movement(treaty_id="ZZ", booking_date=date(2020, 1, 1)),  # left to DV-RTR-05
            ],
            "reinsurance_treaties": [treaty()],
            "claims": [claim(), claim(claim_id="2", occurrence_date=date(2023, 6, 1))],
        },
        3,
        2,
    ),
    "DV-RTR-07": (
        {"reinsurance_transactions": [movement(**PAID), movement()], "claims": [claim()]},
        {
            "reinsurance_transactions": [movement(**PAID), movement(claim_id="9")],
            "claims": [claim()],
        },
        2,
        1,
    ),
    "DV-RTR-08": (
        {
            "reinsurance_transactions": [movement(**PAID), movement(amount=8.0, **HELD)],
            "claim_valuations": [cv(2, paid_to_date=5.0), cv(3, paid_to_date=6.0)],
        },
        {
            "reinsurance_transactions": [
                movement(amount=7.0, **PAID),
                movement(amount=12.0, booking_date=date(2024, 3, 5), **HELD),
            ],
            "claim_valuations": [
                cv(1, paid_to_date=0.0),
                cv(2, paid_to_date=5.0),  # ceded paid 7 above paid 5
                cv(3, paid_to_date=7.0),  # ceded reserve 12 above reserve 10
                cv(1, claim_id="2"),  # a claim without movements is not checked
            ],
        },
        3,
        2,
    ),
    "DV-RTR-09": (
        {
            "reinsurance_transactions": [movement(**PAID)],
            "claim_valuations": [cv(1, ceded_paid_to_date=0.0), cv(2, ceded_paid_to_date=5.0)],
        },
        {
            "reinsurance_transactions": [movement(**PAID), movement(amount=3.0, **HELD)],
            "claim_valuations": [
                cv(1, ceded_paid_to_date=0.0, ceded_reserve=0.0),
                cv(2, ceded_paid_to_date=4.0, ceded_reserve=3.0),
                cv(3, ceded_paid_to_date=5.0, ceded_reserve=3.0),
            ],
        },
        3,
        1,
    ),
    "DV-RTR-10": (
        {"reinsurance_transactions": [movement(), movement(amount=-3.0, **HELD)]},
        {
            "reinsurance_transactions": [
                movement(),
                movement(amount=-5.0),
                movement(amount=0.0, type="RI_COMMISSION"),
                movement(amount=-3.0, **HELD),
            ]
        },
        3,
        2,
    ),
    "DV-RTR-11": (
        {
            "reinsurance_transactions": [movement(line="X")],
            "premiums": [premium(type="CEDED_PREMIUM", booking_date=date(2024, 2, 20))],
            "policies": [policy()],
        },
        {
            "reinsurance_transactions": [
                movement(line="X"),
                movement(line="X", booking_date=date(2024, 3, 5), amount=9.0),
            ],
            "premiums": [
                premium(type="CEDED_PREMIUM", booking_date=date(2024, 2, 20)),
                premium(type="CEDED_PREMIUM", booking_date=date(2024, 3, 20), amount=8.0),
                premium(),  # written premium is no part of the comparison
            ],
            "policies": [policy()],
        },
        2,
        1,
    ),
    "DV-RCV-05": (
        {"recoveries": [recovery()], "claim_valuations": [cv()]},
        {"recoveries": [recovery(), recovery(claim_id="9")], "claim_valuations": [cv()]},
        2,
        1,
    ),
    "DV-RCV-06": (
        {"recoveries": [recovery()], "claim_valuations": [cv()], "claims": [claim()]},
        {
            "recoveries": [recovery(), recovery(booking_date=date(2024, 1, 11))],
            "claim_valuations": [cv()],
            "claims": [claim()],
        },
        2,
        1,
    ),
    "DV-RCV-07": (
        {"recoveries": [recovery()], "claim_valuations": [cv(2, paid_to_date=4.0)]},
        {
            "recoveries": [
                recovery(),
                recovery(amount=3.0),
                recovery(claim_id="2"),
                recovery(claim_id="2", amount=90.0, booking_date=date(2024, 6, 1)),  # after cut-off
            ],
            "claim_valuations": [
                cv(2, paid_to_date=5.0),
                cv(3, paid_to_date=6.0),  # recovered 7 above paid 6
                cv(3, claim_id="2", paid_to_date=4.0),
            ],
        },
        2,
        1,
    ),
    "DV-RCV-08": (
        {
            "recoveries": [recovery(), recovery(type="RECOVERY_OTHER", amount=99.0)],
            "claim_valuations": [cv(1, subrogation_to_date=0.0), cv(2, subrogation_to_date=4.0)],
        },
        {
            "recoveries": [recovery(), recovery(type="RECOVERY_SALVAGE", amount=2.0)],
            "claim_valuations": [
                cv(1, subrogation_to_date=0.0, salvage_to_date=0.0),
                cv(2, subrogation_to_date=4.0, salvage_to_date=2.5),
                cv(3, subrogation_to_date=6.0, salvage_to_date=2.0),
            ],
        },
        6,
        2,
    ),
    "DV-RCV-09": (
        {"recoveries": [recovery()]},
        {"recoveries": [recovery(), recovery(amount=-4.0), recovery(amount=0.0)]},
        3,
        2,
    ),
    "DV-LDG-03": (
        {"ledger": [balance()]},
        {"ledger": [balance(), balance(currency="tl"), balance(currency=None)]},
        2,
        1,
    ),
    "DV-LDG-06": (
        {"ledger": [balance(**FULL), balance(opening_balance=1.0)]},
        {
            "ledger": [
                balance(**FULL),
                balance(closing_balance=10.02, **FULL),
                balance(closing_balance=10.01, **FULL),  # within 0.01
                balance(opening_balance=1.0),  # not all four present
            ]
        },
        3,
        1,
    ),
    "DV-LDG-07": (
        {
            "ledger": [
                balance(12, opening_balance=3.0, period=date(2023, 12, 31)),
                balance(1, opening_balance=0.0),  # year start of an income account
                balance(2, opening_balance=10.0),
            ]
        },
        {
            "ledger": [
                balance(1, opening_balance=0.0),
                balance(2, opening_balance=10.0),
                balance(3, opening_balance=12.0),  # differs from the closing of February
                balance(5, opening_balance=11.0),  # April is missing: the break shows the gap
                balance(1, account="200", opening_balance=5.0),  # first row of its account
            ]
        },
        3,
        2,
    ),
    "DV-LDG-08": (
        {"ledger": [balance(), balance(account="200", closing_balance=-10.0)]},
        {
            "ledger": [
                balance(),
                balance(account="200", closing_balance=-10.0),
                balance(2),
                balance(2, account="200", closing_balance=-9.0),
            ]
        },
        2,
        1,
    ),
    "DV-LDG-10": (
        {"ledger": [balance(1), balance(2), balance(3, entity="F")]},
        {"ledger": [balance(1), balance(4), balance(2, entity="F"), balance(3, entity="F")]},
        6,
        2,
    ),
}


def _run(rule: str, rows: Rows, cut_off: date | None = date(2024, 3, 31)):
    return FEED_CHECKS[rule](Context(frames(rows), SPECS, cut_off))


def test_every_check_has_a_case() -> None:
    assert set(CASES) | set(NOT_BUILT) == set(FEED_CHECKS)


@pytest.mark.parametrize("rule", sorted(CASES))
def test_passing_frames_have_no_failure(rule: str) -> None:
    outcome = _run(rule, CASES[rule][0])
    assert outcome is not None and outcome.checked > 0
    assert outcome.failed == 0 and outcome.refs == ()


@pytest.mark.parametrize("rule", sorted(CASES))
def test_failing_frames_are_counted_with_source_rows(rule: str) -> None:
    _, rows, checked, failed = CASES[rule]
    outcome = _run(rule, rows)
    assert outcome is not None
    assert (outcome.checked, outcome.failed) == (checked, failed)
    assert 0 < len(outcome.refs) <= failed and all(r.file == "f.xlsx" for r in outcome.refs)


@pytest.mark.parametrize("rule", sorted(CASES))
def test_rule_is_in_the_spec_and_names_its_concept(rule: str) -> None:
    owner = next(c for c, s in SPECS.items() if any(r.id == rule for r in s.validation))
    assert _run(rule, CASES[rule][1]).concept == owner  # type: ignore[union-attr]


@pytest.mark.parametrize("rule", sorted(set(NEEDS) - {"DV-RCV-06"}))
def test_a_rule_about_two_feeds_is_not_evaluated_without_the_second(rule: str) -> None:
    owner = next(c for c, s in SPECS.items() if any(r.id == rule for r in s.validation))
    assert _run(rule, {owner: CASES[rule][1][owner]}) is None


def test_dv_rcv_06_uses_the_first_valuation_when_claims_is_not_loaded() -> None:
    rows = {
        "recoveries": [recovery(), recovery(booking_date=date(2024, 1, 11))],
        "claim_valuations": [cv(1), cv(2)],
    }
    outcome = _run("DV-RCV-06", rows)
    assert (outcome.checked, outcome.failed) == (2, 1)  # type: ignore[union-attr]


def test_dv_rtr_06_reads_a_risks_attaching_treaty_by_the_policy_start() -> None:
    rows = {
        "reinsurance_transactions": [movement(**PAID)],
        "reinsurance_treaties": [treaty(attachment_basis="RISKS_ATTACHING")],
        "claims": [claim(policy_id="P1")],
        "policies": [policy(start_date=date(2023, 7, 1))],  # the loss is in 2024, the risk not
    }
    outcome = _run("DV-RTR-06", rows)
    assert (outcome.checked, outcome.failed) == (1, 1)  # type: ignore[union-attr]


def test_dv_rtr_11_is_not_evaluated_when_premiums_hold_no_ceded_rows() -> None:
    rows = {
        "reinsurance_transactions": [movement()],
        "premiums": [premium()],
        "policies": [policy()],
    }
    assert _run("DV-RTR-11", rows) is None


def test_dv_rcv_08_names_the_largest_differences_and_points_at_the_valuation_rows() -> None:
    outcome = _run("DV-RCV-08", CASES["DV-RCV-08"][1])
    assert outcome is not None
    assert "the transactions are used" in outcome.message
    assert "RECOVERY_SUBROGATION at 2024-03-31: booked 4.00, to-date field 6.00" in outcome.message
    assert [r.row for r in outcome.refs] == [3, 4]  # rows of claim_valuations


# --- through the quality engine -----------------------------------------------------------


def _report(rows: Rows):
    built = frames(rows)
    loaded = {
        c: CanonicalFeed(c, "1", f, tuple(x for x in f.columns if not x.startswith("_")), ())
        for c, f in built.items()
    }
    return evaluate(CATALOGUE, loaded, built)


@pytest.mark.parametrize(
    ("rule", "severity"),
    [
        ("DV-RTY-05", "BLOCKING"),
        ("DV-RTR-05", "WARNING"),
        ("DV-RCV-09", "INFO"),
        ("DV-LDG-06", "WARNING"),
    ],
)
def test_one_rule_of_each_feed_becomes_a_finding_of_the_quality_report(rule, severity) -> None:
    rows = {"claim_valuations": [cv()], **CASES[rule][1]}
    report = _report(rows)
    found = next(f for f in report.findings if f.rule == rule)
    assert found.severity == severity
    assert (found.checked, found.count) == CASES[rule][2:]
    assert found.refs and found.refs[0].file == "f.xlsx"
    concept = found.concept
    assert next(c for c in report.coverage if c.concept == concept).loaded


def test_the_report_says_which_second_feed_is_missing_and_what_is_not_built() -> None:
    rows = {
        "claim_valuations": [cv()],
        "reinsurance_transactions": [movement()],
        "ledger": [balance()],
    }
    why = dict(_report(rows).not_evaluated)
    assert why["DV-RTR-05"] == "reinsurance_treaties is not loaded"
    assert why["DV-RTR-06"] == "reinsurance_treaties and claims are not loaded"
    assert why["DV-RTR-11"] == "premiums and policies are not loaded"
    assert "CV12" in why["DV-LDG-09"]
    assert why["DV-RCV-01"] == "recoveries is not loaded"


def test_impacts_name_built_modules_only() -> None:
    """A rule of a feed that only M08 or M10 will use has no impact listed until that module is
    built (record 0381)."""
    report = _report({"claim_valuations": [cv()], **CASES["DV-LDG-06"][1]})
    found = next(f for f in report.findings if f.rule == "DV-LDG-06")
    assert set(found.modules) <= set(CATALOGUE.modules)
    assert not {"M08", "M10"} & set(found.modules)
