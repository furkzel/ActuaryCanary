"""A1b, R08 and R09 (records 0776, 0777): the factors the rule set to 1.000 and the tail used,
as the line page and the rules KF42 and KF43 read them. Hand fixture of tests/fixtures/hand."""

import pytest

from actuarycanary.methods.assumptions import Assumption, AssumptionsRegister
from actuarycanary.methods.chain_ladder import ChainLadder
from actuarycanary.methods.diagnostics import chain_ladder_diagnostics
from actuarycanary.modules.reserving import ChainLadderSettings, MethodInputs, run_reserving
from actuarycanary.report import language
from actuarycanary.report.sensitivity import run_sensitivity, selected_unpaid
from actuarycanary.report.thin_tail import (
    TAIL_FITTED_LIMIT,
    TAIL_OPEN_SHARE_LIMIT,
    add_thin_tail_facts,
    open_claim_share,
    tail_box,
    tail_source,
    thin_factors,
)
from tests.methods.helpers import HAND, HAND_AGES, HAND_ORIGINS, array
from tests.modules.test_reserving_wiring import NO_RULE, PREMIUM, _set

SCOPE = ("S", "L")


def _run(settings: ChainLadderSettings | None = None, register=None):
    settings = settings or ChainLadderSettings()
    register = register or AssumptionsRegister()
    inputs = MethodInputs(premium=PREMIUM, register=register)
    return run_reserving(_set(), settings, inputs), register


def _tables(result, register):
    return {"sensitivity.csv": run_sensitivity(result, register, "no uncertainty in this test")}


def test_the_thin_average_row_puts_the_average_back_and_equals_the_run_without_the_rule() -> None:
    ruled, register = _run()
    plain, _ = _run(NO_RULE)
    frame = _tables(ruled, register)["sensitivity.csv"]
    row = frame.filter(frame["variant"] == "thin_average").to_dicts()
    assert len(row) == 1 and row[0]["line"] == "L"
    group, other = ruled.groups[0], plain.groups[0]
    assert row[0]["base"] == pytest.approx(selected_unpaid(group))
    assert row[0]["value"] == pytest.approx(selected_unpaid(other))
    assert row[0]["difference"] == pytest.approx(row[0]["value"] - row[0]["base"])
    assert row[0]["difference"] != 0
    assert "selected unpaid" in row[0]["quantity"]


def test_the_thin_average_row_has_a_reason_when_the_rule_replaced_nothing() -> None:
    plain, register = _run(NO_RULE)
    frame = _tables(plain, register)["sensitivity.csv"]
    row = frame.filter(frame["variant"] == "thin_average").to_dicts()
    assert len(row) == 1 and row[0]["value"] is None and "replaced no" in row[0]["note"]


def test_the_page_names_the_replaced_factors_with_the_average_and_the_change() -> None:
    ruled, register = _run()
    group = ruled.groups[0]
    found = thin_factors(_tables(ruled, register), group)
    assert found is not None
    paid = group.chain_ladder["paid"]
    assert isinstance(paid, ChainLadder) and paid.replaced[-1]
    assert any("36-48" in n and "1 link ratio" in n and "1.100" in n for n in found["notes"])
    assert "instead of" in found["effect"]
    plain, _ = _run(NO_RULE)
    assert thin_factors({}, plain.groups[0]) is None


def test_the_page_is_written_in_turkish_too() -> None:
    ruled, register = _run()
    with language.using("tr"):
        found = thin_factors(_tables(ruled, register), ruled.groups[0])
    assert found is not None and "bağlantı oranına dayanır" in found["notes"][0]


def test_thin_factor_is_a_warning_and_replaces_few_link_ratios_for_that_column() -> None:
    ruled, _ = _run()
    group = ruled.groups[0]
    codes = [(d.measure, d.item.code, d.item.target) for d in group.diagnostics]
    assert ("paid", "THIN_FACTOR", "36-48") in codes
    assert ("paid", "FEW_LINK_RATIOS", "36-48") not in codes  # said once
    assert ("paid", "FEW_LINK_RATIOS", "24-36") in codes  # two ratios: stated, not replaced
    item = next(d.item for d in group.diagnostics if d.item.code == "THIN_FACTOR")
    assert item.severity == "WARNING" and "1 link ratio, fewer than 2" in item.message
    plain, _ = _run(NO_RULE)
    assert "THIN_FACTOR" not in {d.item.code for d in plain.groups[0].diagnostics}


def test_a_function_level_chain_gives_the_diagnostic_from_the_chain_alone() -> None:
    chain = ChainLadderFor.paid(min_link_ratios=3)
    found = chain_ladder_diagnostics(chain, array(HAND["paid"]), HAND_ORIGINS, HAND_AGES).warnings
    assert [d.target for d in found if d.code == "THIN_FACTOR"] == ["24-36", "36-48"]


class ChainLadderFor:
    @staticmethod
    def paid(**options) -> ChainLadder:
        from actuarycanary.methods.chain_ladder import chain_ladder

        result = chain_ladder(array(HAND["paid"]), **options)
        assert isinstance(result, ChainLadder)
        return result


def test_the_tail_box_says_where_the_tail_comes_from() -> None:
    ruled, register = _run()
    group = ruled.groups[0]
    box = tail_box(_tables(ruled, register), group, None, None)
    assert [r["measure"] for r in box["rows"]] == ["paid", "incurred"]
    assert {r["source"] for r in box["rows"]} == {"MT02 default"}
    assert {r["tail"] for r in box["rows"]} == {"1.000"}
    assert any("default 1.000" in n and "not an estimate" in n for n in box["notes"])
    assert any("not available" in n and "no claim counts" in n for n in box["notes"])
    assert any("does not choose" in n for n in box["notes"])


def test_a_run_setting_and_a_register_entry_are_named_as_such() -> None:
    setting, _ = _run(ChainLadderSettings(tail_factor=1.05))
    assert tail_source(setting.groups[0], "paid") == ("run setting", False)
    entry = Assumption(
        method="MT02", name="tail_factor", scope="S/L/paid", target="", value=1.1,
        who="actuary A", why="reviewed with claims",
    )  # fmt: skip
    entered, _ = _run(register=AssumptionsRegister(entries=(entry,)))
    assert tail_source(entered.groups[0], "paid") == (
        "assumptions register, entered by actuary A",
        False,
    )
    assert tail_source(entered.groups[0], "incurred") == ("MT02 default", True)


def test_without_claim_counts_the_open_share_says_why() -> None:
    ruled, _ = _run()
    share, open_, reported, reason = open_claim_share(None, ruled.groups[0])
    assert (share, open_, reported) == (None, 0, 0) and "no claim counts" in reason


def test_the_facts_of_the_rules_come_from_the_run() -> None:
    ruled, register = _run()
    group = ruled.groups[0]
    facts: dict = {}
    add_thin_tail_facts(facts, _tables(ruled, register), group, None)
    assert facts["thin_factor_count"].value >= 1
    assert "paid 36-48" in facts["thin_factor_list"].value
    assert facts["thin_unpaid_change_size"].value > 0
    assert facts["thin_unpaid_direction"].value in {"more", "less"}
    assert facts["tail_default"].value == 1
    assert facts["tail_default_concern"].value == 0  # no claim counts, no fitted tail here
    assert facts["tail_default_reasons"].value == ""
    assert "open_claim_share" not in facts
    plain, _ = _run(NO_RULE)
    quiet: dict = {}
    add_thin_tail_facts(quiet, {}, plain.groups[0], None)
    assert quiet["thin_factor_count"].value == 0 and "thin_unpaid_change_size" not in quiet


def test_the_limits_of_the_tail_rule_are_stated() -> None:
    assert (TAIL_OPEN_SHARE_LIMIT, TAIL_FITTED_LIMIT) == (0.10, 0.05)
