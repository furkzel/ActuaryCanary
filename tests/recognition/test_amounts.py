"""Cumulative or incremental claim amounts: detected from the values, shown for confirmation,
accumulated by the canonical step and remembered by the mapping profile (record 0223)."""

from datetime import date
from pathlib import Path

import polars as pl
import pytest
from rich.console import Console

from actuarycanary.canonical.amounts import INCREMENTAL, TO_DATE, accumulate
from actuarycanary.canonical.feeds import canonicalise
from actuarycanary.cli.confirm import confirm_tables, show
from actuarycanary.io.excel import SOURCE_ROW
from actuarycanary.recognition.amounts import (
    FALL_SHARE,
    MIN_PAIRS,
    detect_amounts,
    measure,
)
from actuarycanary.recognition.mapping_profiles import dump_profile, load_profile, save_profile
from actuarycanary.recognition.tables import (
    Source,
    canonical_table,
    recognise_table,
    to_profile,
    with_amounts,
    with_concept,
    with_profile,
)
from tests.recognition.build import DICTIONARY, SPECS, table

DAY = date(2026, 10, 23)
CLAIMS = 12  # claims in the fixtures; each has 6 monthly rows, so 5 pairs per claim


def _paid_by_claim() -> list[list[float]]:
    """Cumulative paid of 12 claims over 6 months: a payment pattern that never falls."""
    return [
        [0.0, 100.0 * k, 100.0 * k, 100.0 * k + 40.0, 100.0 * k + 40.0, 100.0 * k + 90.0]
        for k in range(1, CLAIMS + 1)
    ]


def _columns(paid: list[list[float]]) -> dict[str, list]:
    months = [date(2024, m, 28) for m in range(1, 7)]
    return {
        "claim_id": [f"C{k:02d}" for k in range(len(paid)) for _ in months],
        "valuation_date": [d.isoformat() for _ in paid for d in months],
        "paid_to_date": [v for row in paid for v in row],
        "case_reserve": [10.0] * (len(paid) * len(months)),
        "status": ["OPEN"] * (len(paid) * len(months)),
        "currency": ["TRY"] * (len(paid) * len(months)),
    }


def _increments(paid: list[list[float]]) -> list[list[float]]:
    return [[row[0], *[b - a for a, b in zip(row, row[1:], strict=False)]] for row in paid]


CUMULATIVE = _paid_by_claim()
PER_PERIOD = _increments(CUMULATIVE)


def _recognised(paid: list[list[float]]):
    raw = table(_columns(paid))
    return raw, recognise_table(raw, "claim_valuations.xlsx", DICTIONARY)


def test_cumulative_amounts_never_fall_so_they_are_read_as_to_date() -> None:
    raw, rec = _recognised(CUMULATIVE)
    assert rec.source is Source.CANONICAL
    found = detect_amounts(rec, raw)
    assert found.amounts == TO_DATE and found.source is Source.CANONICAL
    assert found.amounts_note.startswith("0 of 48 amounts")


def test_amounts_per_period_are_detected_from_the_values() -> None:
    raw, rec = _recognised(PER_PERIOD)
    found = detect_amounts(rec, raw)
    assert found.amounts == INCREMENTAL
    assert found.amounts_note.startswith("24 of 24 amounts that follow a positive amount")
    assert "per period" in found.amounts_note
    # a sheet in the canonical layout is put up for confirmation like any other proposal
    assert rec.source is Source.CANONICAL and found.source is Source.AUTOMATIC


def test_the_evidence_is_the_share_of_falls_among_amounts_after_a_positive_one() -> None:
    frame = pl.DataFrame(
        {
            "claim_id": ["A"] * 5 + ["B"] * 3,
            "valuation_date": [date(2024, m, 28) for m in (1, 2, 3, 4, 5)]
            + [date(2024, m, 28) for m in (1, 2, 3)],
            "paid_to_date": [0.0, 5.0, 3.0, 3.0, 9.0, 1.0, 2.0, 0.5],
        }
    )
    evidence = measure(frame)  # pairs after a positive amount: 5>3 fall, 3=3, 3<9, 1<2, 2>0.5 fall
    assert (evidence.pairs, evidence.falls) == (5, 2)
    assert evidence.share == pytest.approx(0.4)
    assert not evidence.incremental  # fewer than MIN_PAIRS pairs: the values do not decide


def test_too_few_amounts_or_too_few_falls_do_not_decide() -> None:
    few = measure(
        pl.DataFrame(
            {
                "claim_id": ["A"] * 4,
                "valuation_date": [date(2024, m, 28) for m in (1, 2, 3, 4)],
                "paid_to_date": [5.0, 3.0, 2.0, 1.0],
            }
        )
    )
    assert few.share == 1.0 and few.pairs < MIN_PAIRS and not few.incremental
    rising = [[*row[:-1], row[-1]] for row in CUMULATIVE]
    rising[0][3] = 10.0  # one claim with one fault: one fall in 48
    raw, rec = _recognised(rising)
    assert detect_amounts(rec, raw).amounts == TO_DATE
    assert FALL_SHARE > 1 / 48


def test_other_concepts_and_unreadable_values_stay_to_date() -> None:
    raw = table({"claim_id": ["A", "B"], "paid_to_date": ["x", "y"], "valuation_date": ["a", "b"]})
    rec = recognise_table(raw, "claim_valuations.xlsx", DICTIONARY)
    assert detect_amounts(rec, raw).amounts == TO_DATE


def test_accumulating_adds_the_periods_up_per_claim_in_date_order() -> None:
    frame = pl.DataFrame(
        {
            "claim_id": ["A", "A", "A", "B", "B"],
            "valuation_date": [date(2024, 3, 31), date(2024, 1, 31), date(2024, 2, 29)]
            + [date(2024, 1, 31), date(2024, 2, 29)],
            "paid_to_date": [5.0, 10.0, None, 7.0, 3.0],
            "ceded_paid_to_date": [1.0, 2.0, 0.0, 0.0, 0.0],
            "case_reserve": [50.0, 60.0, 55.0, 9.0, 8.0],
            SOURCE_ROW: [2, 3, 4, 5, 6],
        }
    )
    result = accumulate(frame)
    assert result[SOURCE_ROW].to_list() == [2, 3, 4, 5, 6]  # back in source order
    # A in date order: 10 (Jan), empty (Feb), 5 (Mar) -> 10, empty, 15; B: 7, 10
    assert result["paid_to_date"].to_list() == [15.0, 10.0, None, 7.0, 10.0]
    assert result["ceded_paid_to_date"].to_list() == [3.0, 2.0, 2.0, 0.0, 0.0]
    assert result["case_reserve"].to_list() == frame["case_reserve"].to_list()  # a stock


def test_the_canonical_step_adds_up_after_removing_repeated_rows() -> None:
    raw = table(_columns(PER_PERIOD[:2]))
    spec = SPECS.data["claim_valuations"]
    plain = canonicalise(
        canonical_table(raw, recognise_table(raw, "f.xlsx", DICTIONARY), DICTIONARY)[0], spec
    )
    cumulative = canonicalise(
        canonical_table(raw, recognise_table(raw, "f.xlsx", DICTIONARY), DICTIONARY)[0],
        spec,
        INCREMENTAL,
    )
    expected = [row for claim in CUMULATIVE[:2] for row in claim]
    assert cumulative.frame["paid_to_date"].to_list() == expected
    assert plain.frame["paid_to_date"].to_list() == [v for c in PER_PERIOD[:2] for v in c]
    added = [f for f in cumulative.findings if f.rule == "CV07-INCREMENTAL"]
    assert len(added) == 1 and added[0].severity == "INFO" and added[0].count == 12
    assert not [f for f in plain.findings if f.rule == "CV07-INCREMENTAL"]

    repeated = _columns(PER_PERIOD[:1])
    doubled = {key: [*values, values[-1]] for key, values in repeated.items()}  # last row twice
    twice = table(doubled)
    feed = canonicalise(
        canonical_table(twice, recognise_table(twice, "f.xlsx", DICTIONARY), DICTIONARY)[0],
        spec,
        INCREMENTAL,
    )
    assert feed.frame["paid_to_date"].to_list() == CUMULATIVE[0]  # the repeat added nothing


def test_the_profile_remembers_the_amounts_and_is_not_asked_again(tmp_path: Path) -> None:
    raw, rec = _recognised(PER_PERIOD)
    rec = detect_amounts(rec, raw)
    profile = to_profile(rec, DAY)
    assert profile.amounts == INCREMENTAL
    path = save_profile(tmp_path, profile)
    assert "amounts: incremental" in path.read_text(encoding="utf-8")
    loaded = load_profile(tmp_path, rec.fingerprint)
    assert loaded is not None
    again = recognise_table(raw, "claim_valuations.xlsx", DICTIONARY)
    applied = with_profile(again, loaded[0], loaded[1], DICTIONARY)
    assert applied.amounts == INCREMENTAL and applied.amounts_decided
    assert applied.amounts_note.startswith("saved profile")
    assert detect_amounts(applied, raw) == applied  # not looked at again
    # a user's "cumulative" survives data that looks per period
    chosen = with_amounts(detect_amounts(again, raw), TO_DATE)
    assert detect_amounts(chosen, raw).amounts == TO_DATE
    assert to_profile(chosen, DAY).amounts == TO_DATE


def test_a_profile_without_a_decision_lets_the_values_decide_and_stays_quiet_in_yaml() -> None:
    raw = table({"claim_id": ["A"], "name": ["x"]})
    other = recognise_table(raw, "f.xlsx", DICTIONARY)
    profile = to_profile(other, DAY)
    assert profile.amounts is None and "amounts" not in dump_profile(profile)
    older = _recognised(PER_PERIOD)[1]
    saved = to_profile(older, DAY)  # as a 1.0 profile was: no decision recorded
    assert saved.amounts == TO_DATE  # `to_profile` records what the recognition says
    undecided = saved.model_copy(update={"amounts": None})
    applied = with_profile(
        recognise_table(table(_columns(PER_PERIOD)), "f.xlsx", DICTIONARY),
        undecided,
        "sha",
        DICTIONARY,
    )
    assert not applied.amounts_decided
    assert detect_amounts(applied, table(_columns(PER_PERIOD))).amounts == INCREMENTAL


def test_changing_the_concept_looks_at_the_values_again() -> None:
    raw, rec = _recognised(PER_PERIOD)
    detected = detect_amounts(rec, raw)
    assert detected.amounts == INCREMENTAL
    other = with_concept(detected, "claims", raw, DICTIONARY)
    assert other.amounts == TO_DATE and not other.amounts_decided
    back = detect_amounts(with_concept(other, "claim_valuations", raw, DICTIONARY), raw)
    assert back.amounts == INCREMENTAL
    with pytest.raises(ValueError, match="only claim_valuations"):
        with_amounts(other, INCREMENTAL)
    with pytest.raises(ValueError, match="to_date or incremental"):
        with_amounts(back, "sometimes")


def test_the_confirmation_screen_says_which_kind_of_amounts_it_found() -> None:
    raw, rec = _recognised(PER_PERIOD)
    console = Console(record=True, width=120)
    show(console, detect_amounts(rec, raw), DICTIONARY)
    text = console.export_text()
    assert "Amounts: per period, not cumulative" in text
    assert "amounts=to_date" in text
    quiet = Console(record=True, width=120)
    cumulative_raw, cumulative = _recognised(CUMULATIVE)
    show(quiet, detect_amounts(cumulative, cumulative_raw), DICTIONARY)
    assert "Amounts: cumulative to the valuation date" in quiet.export_text()


def test_the_user_can_set_the_amounts_on_the_confirmation_screen(monkeypatch) -> None:  # noqa: ANN001
    raw, rec = _recognised(PER_PERIOD)
    answers = iter(["e", "amounts=to_date", ""])
    monkeypatch.setattr(
        "actuarycanary.cli.confirm.Prompt.ask", lambda *args, **kwargs: next(answers)
    )
    console = Console(record=True, width=120)
    result = confirm_tables(console, [(detect_amounts(rec, raw), raw)], DICTIONARY)
    assert result[0].amounts == TO_DATE and result[0].amounts_decided
