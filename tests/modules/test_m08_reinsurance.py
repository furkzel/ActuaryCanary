"""M08 Reinsurance: the treaty table, the reconciliation with the reported ceded amounts, the
allocation table, the size bands, the settings, and the skip without treaties.

Spec IDs proved: M08, MT21, CV09.
"""

import pytest
from pydantic import ValidationError

from actuarycanary.convert.allocation import BY_WRITTEN, GIVEN
from actuarycanary.modules.reinsurance import ReinsuranceSettings, reinsurance_run
from actuarycanary.pipeline import RunResult
from tests.measures.reinsurance_book import book


def test_treaty_table_puts_computed_beside_reported() -> None:
    run = reinsurance_run(book())
    assert run is not None
    table = {r["treaty_id"]: r for r in run.treaty_table().iter_rows(named=True)}
    qs, xl = table["QS"], table["XL"]
    assert qs["gross_incurred"] == pytest.approx(950.0)
    assert qs["computed_ceded_incurred"] == pytest.approx(285.0)
    assert qs["reported_ceded_incurred"] == pytest.approx(285.0)
    assert xl["computed_ceded_incurred"] == pytest.approx(160.0)
    assert xl["computed_ceded_paid"] == pytest.approx(80.0)
    assert xl["computed_ceded_premium"] == pytest.approx(35.0)
    assert xl["reported_ceded_premium"] == pytest.approx(35.0)
    assert qs["computed_commission"] == pytest.approx(60.0) == qs["reported_commission"]
    assert xl["units_hit"] == 2 and xl["units_exhausted"] == 0
    reconciliation = run.reconciliation()
    assert not reconciliation["differs"].any()


def test_a_built_difference_shows_with_its_rows_on_both_sides() -> None:
    run = reinsurance_run(book(qs_paid_d=100.0))
    assert run is not None
    rows = run.reconciliation()
    year = rows.filter((rows["level"] == "treaty year") & (rows["treaty_id"] == "QS")).row(
        0, named=True
    )
    assert year["differs"] and year["difference"] == pytest.approx(20.0)
    assert year["computed_ceded_incurred"] == pytest.approx(285.0)
    claim = rows.filter(rows["level"] == "claim").row(0, named=True)
    assert claim["claim_id"] == "D" and claim["reported_ceded_incurred"] == pytest.approx(130.0)
    # the layer agrees: no row of its own
    assert rows.filter(rows["treaty_id"] == "XL")["differs"].to_list() == [False]


def test_allocation_table_and_size_bands() -> None:
    run = reinsurance_run(book())
    assert run is not None
    table = run.allocation_table()
    qs = table.filter(table["treaty_id"] == "QS")
    methods = dict(zip(qs["type"], qs["method"], strict=False))
    assert methods["CEDED_CLAIM_PAID"] == GIVEN and methods["CEDED_PREMIUM"] == BY_WRITTEN
    premium = table.filter((table["treaty_id"] == "QS") & (table["type"] == "CEDED_PREMIUM"))
    assert premium["amount"].sum() == pytest.approx(300.0) and premium["year"].to_list() == [2024]
    bands = run.size_bands()
    assert set(bands["size_band"]) == {"0 to 10k"} and bands["claims"].max() == 4


def test_settings_accept_the_built_values_only() -> None:
    assert ReinsuranceSettings().index_clause == "payment_by_payment"
    for wrong in (
        {"simulate": True},
        {"index_clause": "average_month"},
        {"allocation_fallback": "x"},
        {"inuring_order": "other"},
        {"loss_view": "paid"},
    ):
        with pytest.raises(ValidationError):
            ReinsuranceSettings.model_validate(wrong)


def test_without_treaties_m08_is_skipped_and_writes_nothing(default_run: RunResult) -> None:
    m08 = default_run.analysis.get("M08")
    assert m08.state.value == "skipped"
    assert m08.reasons[0].startswith(
        "Reinsurance did not run: no reinsurance treaties were loaded."
    )
    names = {p.name for p in default_run.folder.iterdir()}
    assert not names & {
        "ceded_by_treaty.csv",
        "ceded_allocation.csv",
        "reinsurance_reconciliation.csv",
    }


def test_what_if_compares_the_loaded_and_an_alternative_programme() -> None:
    from actuarycanary.methods.assumptions import Assumption, AssumptionsRegister
    from actuarycanary.modules.reinsurance_whatif import alternatives, comparison

    def entry(name: str, value: float | str) -> Assumption:
        return Assumption(
            method="MT21",
            name=name,
            scope="QS50",
            target="QS2",
            value=value,
            who="analyst",
            why="a larger quota share",
        )

    register = AssumptionsRegister(
        entries=(
            entry("treaty_type", "QUOTA_SHARE"),
            entry("cession_share", 0.5),
            entry("line", "L"),
            entry("ceding_commission", 0.25),
        )
    )
    inputs = book()
    run = reinsurance_run(inputs)
    assert run is not None
    found = alternatives(register, run.inputs.sections)
    assert [p.name for p in found] == ["QS50"] and found[0].sections[0].inception.year == 2024
    both = run.__class__(
        **{**run.__dict__, "settings": ReinsuranceSettings(programme="both", loss_view="incurred")}
    )
    table, notes = comparison(inputs, both, register)
    rows = {r["programme"]: r for r in table.iter_rows(named=True)}
    assert rows["loaded"]["expected_ceded_loss"] == pytest.approx(445.0)  # 285 + 160
    assert rows["QS50"]["expected_ceded_loss"] == pytest.approx(475.0)
    assert rows["QS50"]["ceded_premium"] == pytest.approx(500.0)
    assert rows["QS50"]["net_result"] == pytest.approx(475.0 + 125.0 - 500.0)
    assert rows["loaded"]["gross_loss"] == rows["QS50"]["gross_loss"] == pytest.approx(950.0)
    assert rows["loaded"]["loss_view"] == "incurred"
    assert not notes
