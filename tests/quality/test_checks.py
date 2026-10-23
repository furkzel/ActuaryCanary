"""Every check of spec/data: one frame that passes and one that fails, built in code."""

from calendar import monthrange
from datetime import date
from typing import Any

import pytest

from actuarycanary.canonical.feeds import Finding
from actuarycanary.quality.checks import CANONICAL_RULES, CHECKS, Context, from_canonical
from tests.quality.builders import SPECS, Rows, claim, cv, expense, frames, policy, premium, series


# rule -> (frames that pass, frames that fail, rows checked in the failing frames, rows failing)
def _monthly(
    values: list[float | None], series_id: str = "USD/TRY", kind: str = "FX_PERIOD_END"
) -> list[dict[str, Any]]:
    """One series row per month from January 2024; None leaves the month out."""
    rows = []
    for month, value in enumerate(values, start=1):
        if value is not None:
            day = date(2024, month, monthrange(2024, month)[1])
            rows.append(series(series_id=series_id, kind=kind, date=day, value=value))
    return rows


def _dollar_claims() -> Rows:
    return {
        "claim_valuations": [cv(1, currency="USD"), cv(2, currency="USD"), cv(3, currency="USD")]
    }


CASES: dict[str, tuple[Rows, Rows, int, int]] = {
    "DV-CLV-07": (
        {"claim_valuations": [cv(1, paid_to_date=100.0), cv(2, paid_to_date=200.0)]},
        {"claim_valuations": [cv(1, paid_to_date=100.0), cv(2, paid_to_date=50.0)]},
        1,
        1,
    ),
    "DV-CLV-08": (
        {"claim_valuations": [cv(case_reserve=0.0)]},
        {"claim_valuations": [cv(), cv(case_reserve=-1.0)]},
        2,
        1,
    ),
    "DV-CLV-09": (
        {"claim_valuations": [cv(status="CLOSED", case_reserve=0.0), cv(2)]},
        {"claim_valuations": [cv(status="CLOSED", case_reserve=5.0)]},
        1,
        1,
    ),
    "DV-CLV-10": (
        {"claim_valuations": [cv(status="CLOSED_NIL", paid_to_date=0.0)]},
        {"claim_valuations": [cv(status="CLOSED_NIL", paid_to_date=5.0)]},
        1,
        1,
    ),
    "DV-CLV-11": (
        {"claim_valuations": [cv(paid_to_date=10.0, ceded_paid_to_date=5.0)]},
        {"claim_valuations": [cv(paid_to_date=10.0, ceded_paid_to_date=20.0)]},
        1,
        1,
    ),
    "DV-CLV-12": (
        {"claim_valuations": [cv(1), cv(2), cv(3, currency="UNKNOWN")]},
        {"claim_valuations": [cv(1), cv(2, currency="USD")]},
        2,
        2,
    ),
    "DV-CLV-13": (
        {"claim_valuations": [cv(1), cv(2), cv(3), cv(1, claim_id="2", status="CLOSED")]},
        {"claim_valuations": [cv(1), cv(3)]},
        1,
        1,
    ),
    "DV-CLV-14": (
        {"claim_valuations": [cv()], "claims": [claim()]},
        {"claim_valuations": [cv(), cv(claim_id="9")], "claims": [claim()]},
        2,
        1,
    ),
    "DV-CLV-15": (
        {"claim_valuations": [cv(1), cv(2, paid_to_date=100.0)]},
        {"claim_valuations": [cv(1), cv(2, paid_to_date=101.0)]},
        1,
        1,
    ),
    "DV-CLM-04": (
        {"claims": [claim(), claim(report_date=None)]},
        {"claims": [claim(report_date=date(2024, 1, 9))]},
        1,
        1,
    ),
    "DV-CLM-05": (
        {"claims": [claim(), claim(close_date=None)]},
        {"claims": [claim(close_date=date(2024, 1, 11))]},
        1,
        1,
    ),
    "DV-CLM-07": (
        {"claims": [claim()], "claim_valuations": [cv(3)]},
        {"claims": [claim(occurrence_date=date(1949, 12, 31)), claim()]},
        2,
        1,
    ),
    "DV-CLM-08": (
        {"claims": [claim()], "claim_valuations": [cv(1)]},
        {"claims": [claim(report_date=date(2024, 2, 5))], "claim_valuations": [cv(1)]},
        1,
        1,
    ),
    "DV-CLM-09": (
        {"claims": [claim(policy_id="P1")], "policies": [policy()]},
        {"claims": [claim(policy_id="P2"), claim(policy_id=None)], "policies": [policy()]},
        1,
        1,
    ),
    "DV-CLM-10": (
        {"claims": [claim(policy_id="P1")], "policies": [policy()]},
        {
            "claims": [claim(policy_id="P1", occurrence_date=date(2025, 1, 1))],
            "policies": [policy()],
        },
        1,
        1,
    ),
    "DV-CLM-11": (
        {"claims": [claim()], "claim_valuations": [cv()]},
        {"claims": [claim(), claim(claim_id="2")], "claim_valuations": [cv()]},
        2,
        1,
    ),
    "DV-POL-01": ({"policies": [policy()]}, {"policies": [policy(policy_id=None)]}, 1, 1),
    "DV-POL-02": (
        {"policies": [policy(), policy(policy_id="P2")]},
        {"policies": [policy(), policy()]},
        2,
        1,
    ),
    "DV-POL-03": ({"policies": [policy()]}, {"policies": [policy(segment=None)]}, 1, 1),
    "DV-POL-04": (
        {"policies": [policy()]},
        {"policies": [policy(end_date=date(2024, 1, 1))]},
        1,
        1,
    ),
    "DV-POL-05": (
        {"policies": [policy(cancellation_date=date(2024, 6, 1)), policy()]},
        {"policies": [policy(cancellation_date=date(2025, 6, 1))]},
        1,
        1,
    ),
    "DV-POL-06": (
        {"policies": [policy()]},
        {"policies": [policy(currency="try"), policy(currency="TRY")]},
        2,
        1,
    ),
    "DV-POL-07": (
        {"policies": [policy(channel="BROKER")]},
        {"policies": [policy(channel="Broker")]},
        1,
        1,
    ),
    "DV-POL-08": (
        {"policies": [policy(sum_insured=0.0)]},
        {"policies": [policy(sum_insured=-5.0)]},
        1,
        1,
    ),
    "DV-PRM-01": ({"premiums": [premium()]}, {"premiums": [premium(policy_id=None)]}, 1, 1),
    "DV-PRM-02": (
        {"premiums": [premium(), premium(transaction_id="T2")]},
        {"premiums": [premium(), premium()]},
        2,
        1,
    ),
    "DV-PRM-03": ({"premiums": [premium()]}, {"premiums": [premium(amount=None)]}, 1, 1),
    "DV-PRM-04": ({"premiums": [premium()]}, {"premiums": [premium(type="ODEME")]}, 1, 1),
    "DV-PRM-05": ({"premiums": [premium()]}, {"premiums": [premium(currency="TL")]}, 1, 1),
    "DV-PRM-06": (
        {"premiums": [premium()], "policies": [policy()]},
        {"premiums": [premium(policy_id="P9")], "policies": [policy()]},
        1,
        1,
    ),
    "DV-PRM-07": (
        {
            "premiums": [premium(), premium(effective_date=date(2024, 12, 31))],
            "policies": [policy()],
        },
        {
            "premiums": [premium(effective_date=date(2025, 1, 1)), premium()],
            "policies": [policy()],
        },
        2,
        1,
    ),
    "DV-PRM-09": (
        {"premiums": [premium()], "policies": [policy()]},
        {"premiums": [premium(currency="USD")], "policies": [policy()]},
        1,
        1,
    ),
    "DV-EXP-01": ({"expenses": [expense()]}, {"expenses": [expense(period=None)]}, 1, 1),
    "DV-EXP-02": ({"expenses": [expense()]}, {"expenses": [expense(currency="x")]}, 1, 1),
    "DV-EXP-03": ({"expenses": [expense()]}, {"expenses": [expense(type="MISC")]}, 1, 1),
    "DV-EXP-04": (
        {"expenses": [expense()]},
        {"expenses": [expense(period=date(2024, 1, 15))]},
        1,
        1,
    ),
    "DV-EXP-05": ({"expenses": [expense()]}, {"expenses": [expense(amount=0.0)]}, 1, 1),
    "DV-EXP-06": (
        {"expenses": [expense(), expense(amount=6.0)]},
        {"expenses": [expense(), expense()]},
        2,
        1,
    ),
    "DV-MKT-01": ({"market": [series()]}, {"market": [series(value=None)]}, 1, 1),
    "DV-MKT-02": (
        {"market": [series(), series(kind="PRICE_INDEX")]},
        {"market": [series(), series()]},
        2,
        1,
    ),
    "DV-MKT-03": ({"market": [series()]}, {"market": [series(value=0.0)]}, 1, 1),
    "DV-MKT-05": ({"market": [series()]}, {"market": [series(kind="spot")]}, 1, 1),
    "DV-MKT-06": (
        {"market": _monthly([30.0, 31.0, 32.0])},
        {"market": _monthly([30.0, None, 32.0])},
        3,
        1,
    ),
    "DV-MKT-07": (
        {**_dollar_claims(), "market": _monthly([30.0, 31.0, 32.0])},
        {**_dollar_claims(), "market": _monthly([30.0, None, 32.0])},
        3,
        1,
    ),
    "DV-MKT-08": (
        {"market": _monthly([100.0, 101.0, 102.0, 103.0, 104.0])},
        {"market": _monthly([100.0, 101.0, 102.0, 103.0, 104.0, 150.0])},
        5,
        1,
    ),
}
CUT_OFF = date(2024, 3, 31)


def _run(rule: str, rows: Rows) -> Any:
    return CHECKS[rule](Context(frames(rows), SPECS, CUT_OFF, reporting_currency="TRY"))


def test_every_check_has_a_case() -> None:
    assert set(CASES) == set(CHECKS)


@pytest.mark.parametrize("rule", sorted(CASES))
def test_passing_frame_has_no_failure(rule: str) -> None:
    outcome = _run(rule, CASES[rule][0])
    assert outcome is not None and outcome.checked > 0
    assert outcome.failed == 0 and outcome.refs == ()


@pytest.mark.parametrize("rule", sorted(CASES))
def test_failing_frame_is_counted_with_source_rows(rule: str) -> None:
    _, rows, checked, failed = CASES[rule]
    outcome = _run(rule, rows)
    assert outcome is not None
    assert (outcome.checked, outcome.failed) == (checked, failed)
    assert len(outcome.refs) == failed and all(r.file == "f.xlsx" for r in outcome.refs)


@pytest.mark.parametrize("rule", sorted(CASES))
def test_rule_is_in_the_spec_and_names_its_concept(rule: str) -> None:
    owner = next(c for c, s in SPECS.items() if any(r.id == rule for r in s.validation))
    assert _run(rule, CASES[rule][1]).concept == owner  # type: ignore[union-attr]


def test_missing_fields_mean_not_evaluated() -> None:
    assert _run("DV-CLV-14", {"claim_valuations": [cv()]}) is None  # claims not loaded
    assert _run("DV-CLV-11", {"claim_valuations": [cv()]}) is None  # no ceded columns
    assert _run("DV-POL-07", {"policies": [{"policy_id": "P1"}]}) is None  # no class field


def test_dv_clv_07_lists_a_decrease_even_when_a_recovery_rose() -> None:
    # paid_to_date excludes recoveries by definition, so a recovery does not explain a decrease
    rows = {
        "claim_valuations": [
            cv(1, paid_to_date=100.0),
            cv(2, paid_to_date=60.0, subrogation_to_date=40.0),
            cv(3, paid_to_date=30.0, subrogation_to_date=45.0),
        ]
    }
    outcome = _run("DV-CLV-07", rows)
    assert (outcome.checked, outcome.failed) == (2, 2)  # type: ignore[union-attr]


def test_example_references_are_limited_to_five_in_row_order() -> None:
    rows = {"premiums": [premium() for _ in range(9)]}
    outcome = _run("DV-PRM-02", rows)
    assert outcome.failed == 8  # type: ignore[union-attr]
    assert [r.row for r in outcome.refs] == [3, 4, 5, 6, 7]  # type: ignore[union-attr]


def test_canonical_findings_become_outcomes_with_references() -> None:
    raw = frames({"claim_valuations": [cv(), cv(2), cv(3)]})["claim_valuations"]
    findings = (Finding("claim_valuations", "DV-CLV-03", "WARNING", 1, "empty currency", (3,)),)
    outcomes = from_canonical("claim_valuations", findings, raw)
    hit = next(o for o in outcomes if o.rule == "DV-CLV-03")
    assert (hit.checked, hit.failed, hit.message) == (3, 1, "empty currency")
    assert [r.row for r in hit.refs] == [3]
    clean = [o for o in outcomes if o.rule != "DV-CLV-03"]
    assert clean and all(o.failed == 0 and o.checked == 3 for o in clean)


def test_every_rule_has_a_check_or_is_applied_by_the_canonical_step() -> None:
    rules = {r.id for spec in SPECS.values() for r in spec.validation}
    canonical = {r for rules_of in CANONICAL_RULES.values() for r in rules_of}
    assert rules - canonical <= set(CHECKS)  # none is left "not implemented"


def test_dv_mkt_06_leaves_daily_rates_alone_and_checks_each_series_on_its_own() -> None:
    rows = {
        "market": [
            series(date=date(2024, 1, 5)),
            series(date=date(2024, 6, 5)),  # FX_SPOT is daily: no month is expected
            *_monthly([1.0, 2.0], "A/B"),
            *_monthly([None, 2.0, None, 3.0], "C/D"),  # starts late, one month missing inside
        ]
    }
    outcome = _run("DV-MKT-06", rows)
    assert (outcome.checked, outcome.failed) == (2 + 3, 1)  # type: ignore[union-attr]
    assert "C/D FX_PERIOD_END 2024-03" in outcome.message  # type: ignore[union-attr]


def test_dv_mkt_07_needs_a_rate_up_to_the_cut_off() -> None:
    claims = _dollar_claims()
    short = _run("DV-MKT-07", {**claims, "market": _monthly([30.0, 31.0])})
    assert (short.checked, short.failed) == (3, 1)  # type: ignore[union-attr]
    assert "2024-03" in short.message  # type: ignore[union-attr]
    late = _run("DV-MKT-07", {**claims, "market": _monthly([None, None, 32.0])})
    assert (late.checked, late.failed) == (3, 2)  # type: ignore[union-attr]


def test_dv_mkt_07_accepts_the_inverse_pair_and_any_fx_kind() -> None:
    market = [*_monthly([None, 0.03], "TRY/USD"), *_monthly([30.0, None, 32.0], kind="FX_SPOT")]
    outcome = _run("DV-MKT-07", {**_dollar_claims(), "market": market})
    assert (outcome.checked, outcome.failed) == (3, 0)  # type: ignore[union-attr]


def test_dv_mkt_07_reports_a_currency_without_any_series_and_skips_the_reporting_one() -> None:
    rows = {**_dollar_claims(), "market": _monthly([1.0, 2.0, 3.0], "EUR/TRY")}
    outcome = _run("DV-MKT-07", rows)
    assert (outcome.checked, outcome.failed, outcome.refs) == (3, 3, ())  # type: ignore[union-attr]
    local = {"claim_valuations": [cv(1), cv(2)], "market": _monthly([1.0, 2.0, 3.0], "EUR/TRY")}
    assert _run("DV-MKT-07", local).checked == 0  # type: ignore[union-attr]


def test_dv_mkt_07_checks_the_price_index_when_the_run_restates_with_it() -> None:
    local = [cv(1), cv(2), cv(3)]
    with_index = frames(
        {"claim_valuations": local, "market": _monthly([100.0, 101.0], "CPI", "PRICE_INDEX")}
    )
    without = frames({"claim_valuations": local, "market": _monthly([1.0], "EUR/TRY")})

    def counts(found: dict[str, Any], adjusted: bool) -> tuple[int, int]:
        outcome = CHECKS["DV-MKT-07"](Context(found, SPECS, CUT_OFF, "TRY", "CPI", adjusted))
        assert outcome is not None
        return outcome.checked, outcome.failed

    assert counts(with_index, adjusted=True) == (3, 1)
    assert counts(with_index, adjusted=False) == (3, 1)  # an index in the data is used by MT07
    assert counts(without, adjusted=False) == (0, 0)  # no index and no restatement: not needed
    assert counts(without, adjusted=True) == (3, 3)  # the run restates but has no index at all


def test_dv_mkt_07_is_not_evaluated_without_the_reporting_currency() -> None:
    rows = {**_dollar_claims(), "market": _monthly([30.0])}
    assert CHECKS["DV-MKT-07"](Context(frames(rows), SPECS, CUT_OFF)) is None


def test_dv_mkt_08_scores_each_series_within_itself() -> None:
    steady = _monthly([100.0 + i for i in range(6)], "A/B")
    jumpy = _monthly([1.0, 1.0, 1.0, 1.0, 5.0, 5.0], "C/D")  # 1 jump among 5 changes
    outcome = _run("DV-MKT-08", {"market": [*steady, *jumpy]})
    assert (outcome.checked, outcome.failed) == (10, 1)  # type: ignore[union-attr]


def test_dv_prm_07_falls_back_to_the_booking_date_and_ignores_unknown_policies() -> None:
    rows = {
        "premiums": [
            premium(
                booking_date=date(2025, 3, 1), effective_date=None
            ),  # no effective date: booking date counts
            premium(transaction_id="T2", policy_id="P9"),  # DV-PRM-06 reports this one
        ],
        "policies": [policy()],
    }
    outcome = _run("DV-PRM-07", rows)
    assert (outcome.checked, outcome.failed) == (1, 1)  # type: ignore[union-attr]
