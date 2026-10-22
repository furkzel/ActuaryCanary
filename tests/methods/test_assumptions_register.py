"""Assumptions register (blueprint section 12) and the judgements of MT02, MT03, MT05, MT07
and MT10 drawn from it: value, default, who, when and why of every entry in force."""

from datetime import date
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from actuarycanary.methods.assumptions import (
    DEFAULT_WHO,
    Assumption,
    AssumptionError,
    AssumptionsRegister,
    parse_cell,
    records,
)
from actuarycanary.methods.chain_ladder import ChainLadder
from actuarycanary.methods.judgement import (
    chain_ladder_judged,
    future_inflation,
    prior_loss_ratios,
    selection_overrides,
)
from actuarycanary.methods.selection import Choice
from tests.methods.helpers import HAND, HAND_AGES, HAND_ORIGINS, array

SCOPE = "NON_LIFE/MOTOR_OD/paid"
WHEN = date(2026, 10, 22)


def _user(method: str, name: str, value, target: str = "", scope: str = SCOPE) -> Assumption:
    return Assumption(
        method=method, name=name, scope=scope, target=target, value=value,
        who="actuary A", when=WHEN, why="reviewed with claims",
    )  # fmt: skip


def _judged(*entries: Assumption, **options) -> tuple[ChainLadder, list[Assumption]]:
    result, used = chain_ladder_judged(
        array(HAND["paid"]),
        origins=HAND_ORIGINS,
        ages=HAND_AGES,
        scope=SCOPE,
        register=AssumptionsRegister(entries=entries),
        **options,
    )
    assert isinstance(result, ChainLadder)
    return result, used


def test_user_entries_need_a_reason() -> None:
    with pytest.raises(ValidationError, match="needs a reason"):
        Assumption(method="MT02", name="tail_factor", value=1.1, who="actuary A")


def test_two_entries_for_the_same_target_are_rejected() -> None:
    entry = _user("MT02", "tail_factor", 1.1)
    with pytest.raises(ValidationError, match="two register entries"):
        AssumptionsRegister(entries=(entry, entry))


def test_the_exact_scope_wins_over_every_scope() -> None:
    general = _user("MT02", "tail_factor", 1.2, scope="*")
    exact = _user("MT02", "tail_factor", 1.1)
    register = AssumptionsRegister(entries=(exact, general))
    assert register.find("MT02", "tail_factor", SCOPE)[""].value == 1.1
    assert register.find("MT02", "tail_factor", "LIFE/GROUP_TERM_LIFE/paid")[""].value == 1.2


def test_defaults_are_recorded_with_who_default() -> None:
    result, used = _judged()
    tail, *factors = used
    assert (tail.name, tail.value, tail.default, tail.who) == ("tail_factor", 1.0, 1.0, DEFAULT_WHO)
    assert [f.target for f in factors] == ["12-24", "24-36", "36-48"]
    assert [f.value for f in factors] == pytest.approx([1.9, 1.2, 1.1])
    assert all(f.value == f.default and f.is_default for f in factors)
    assert result.factors.tolist() == pytest.approx([1.9, 1.2, 1.1])


def test_selected_factor_records_the_average_as_the_alternative() -> None:
    result, used = _judged(_user("MT02", "selected_factor", 1.15, "24-36"))
    entry = next(e for e in used if e.target == "24-36")
    assert (entry.value, entry.default, entry.who, entry.when) == (1.15, 1.2, "actuary A", WHEN)
    assert result.factors[1] == 1.15 and result.averages[1] == pytest.approx(1.2)
    assert result.overridden.tolist() == [False, True, False]
    assert result.cdf[1] == pytest.approx(1.15 * 1.1)


def test_cell_exclusion_by_label() -> None:
    result, used = _judged(_user("MT02", "exclusion", True, "2022:12-24"))
    assert result.factors[0] == pytest.approx(360 / 190)  # as in the MT02 hand fixture
    entry = next(e for e in used if e.name == "exclusion")
    assert (entry.target, entry.value, entry.default) == ("2022:12-24", "excluded", "included")


def test_tail_from_settings_and_from_the_register() -> None:
    _, used = _judged(tail_factor=1.05)
    assert (used[0].value, used[0].who) == (1.05, "run settings")
    result, used = _judged(_user("MT02", "tail_factor", 1.1), tail_factor=1.05)
    assert (used[0].value, used[0].who) == (1.1, "actuary A")
    assert result.tail_factor == 1.1


@pytest.mark.parametrize(
    ("name", "target", "value", "message"),
    [
        ("exclusion", "2030:12-24", True, "not a link ratio"),
        ("exclusion", "2022:12-36", True, "not a link ratio"),
        ("selected_factor", "48-60", 1.0, "no such development column"),
        ("selected_factor", "12-24", "high", "is not a number"),
    ],
)
def test_entries_that_name_nothing_are_errors(name, target, value, message) -> None:
    with pytest.raises(AssumptionError, match=message):
        _judged(_user("MT02", name, value, target))


def test_parse_cell() -> None:
    assert parse_cell("2023:24-36", HAND_ORIGINS, HAND_AGES) == (2, 1)


def test_prior_loss_ratios_user_origin_scope_and_data_derived() -> None:
    register = AssumptionsRegister(
        entries=(
            _user("MT03", "prior_loss_ratio", 0.7, "2024"),
            _user("MT03", "prior_loss_ratio", 0.65, "", scope="*"),
        )
    )
    ratios, sources, used = prior_loss_ratios(
        "MT03", "prior_loss_ratio", HAND_ORIGINS, SCOPE, register, 0.58
    )
    assert ratios.tolist() == [0.65, 0.65, 0.65, 0.7]
    assert sources == ("user",) * 4
    assert [(e.target, e.value) for e in used] == [("", 0.65), ("2024", 0.7)]
    ratios, sources, used = prior_loss_ratios(
        "MT05", "expected_loss_ratio", HAND_ORIGINS, SCOPE, AssumptionsRegister(), 0.58
    )
    assert ratios.tolist() == [0.58] * 4 and set(sources) == {"data-derived prior"}
    assert (used[0].value, used[0].default, used[0].who) == (0.58, "cape_cod", DEFAULT_WHO)
    ratios, sources, used = prior_loss_ratios(
        "MT03", "prior_loss_ratio", HAND_ORIGINS, SCOPE, AssumptionsRegister(), None
    )
    assert np.isnan(ratios).all() and used == []


def test_future_inflation_default_and_user() -> None:
    value, entry = future_inflation(SCOPE, AssumptionsRegister())
    assert value is None and entry.value is None and entry.is_default
    assert "value-date prices only" in entry.why
    register = AssumptionsRegister(entries=(_user("MT07", "future_inflation", 0.3),))
    value, entry = future_inflation(SCOPE, register)
    assert value == 0.3 and entry.who == "actuary A"
    with pytest.raises(AssumptionError, match="not above -100"):
        future_inflation(
            SCOPE, AssumptionsRegister(entries=(_user("MT07", "future_inflation", -1),))
        )


def test_selection_overrides_and_threshold() -> None:
    register = AssumptionsRegister(
        entries=(_user("MT10", "method", "bornhuetter_ferguson", "2022"),)
    )
    overrides, threshold, used = selection_overrides(HAND_ORIGINS, SCOPE, register)
    assert overrides == {1: Choice.BORNHUETTER_FERGUSON} and threshold == 0.5
    assert [(e.name, e.target, e.value) for e in used] == [
        ("bf_below_maturity", "", 0.5),
        ("method", "2022", "bornhuetter_ferguson"),
    ]
    with pytest.raises(AssumptionError, match="allowed"):
        selection_overrides(
            HAND_ORIGINS,
            SCOPE,
            AssumptionsRegister(entries=(_user("MT10", "method", "BF", "2022"),)),
        )


def test_register_from_yaml_and_records(tmp_path: Path) -> None:
    path = tmp_path / "assumptions.yaml"
    path.write_text(
        "entries:\n"
        "  - {method: MT02, name: exclusion, scope: NON_LIFE/PROPERTY/paid, target: '2023:12-24',\n"
        "     value: true, who: actuary A, when: 2026-10-22, why: one large claim reported late}\n",
        encoding="utf-8",
    )
    register = AssumptionsRegister.from_yaml(path)
    [row] = records(register.entries)
    assert row["when"] == "2026-10-22" and row["target"] == "2023:12-24" and row["value"] is True
