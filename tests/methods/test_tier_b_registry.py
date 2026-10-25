"""The tier B registry, seeds and judgements: every spec of P24 has an implementation of its
version, the seed and the defaults reach the run id, every judgement has a register entry.

Spec IDs proved: MT11, MT12, MT13, MT14, MT15, MT16, MT22, AE02 (decisions 0280, 0281)."""

from datetime import date

import numpy as np
import pytest

from actuarycanary.manifest.run import run_id
from actuarycanary.methods import registry
from actuarycanary.methods.assumptions import Assumption, AssumptionError, AssumptionsRegister
from actuarycanary.methods.judgement_tier_b import PARAMETERS, horizons, parameters
from actuarycanary.methods.seeding import generator, key_words
from actuarycanary.spec.loader import load_specs

P24 = ("MT11", "MT12", "MT13", "MT14", "MT15", "MT16", "MT22", "AE02")


def test_every_spec_of_p24_has_an_implementation_of_its_version() -> None:
    planned = load_specs(planned=True)
    assert set(registry.REGISTRY) == set(P24)
    for spec_id in P24:
        entry = registry.get(spec_id)
        spec = planned.methods.get(spec_id) or planned.measures[spec_id]
        assert entry.spec_version == spec.version, spec_id
        assert entry.qualified_name.startswith("actuarycanary.methods."), spec_id
        assert spec.implemented  # wired by the integration (decisions 0280, 0620)
    with pytest.raises(KeyError, match="no tier B implementation"):
        registry.get("MT17")


def test_random_methods_are_declared_and_seeded_in_the_manifest_rows() -> None:
    rows = registry.randomness(seed=9)
    assert [r["method"] for r in rows] == ["MT11", "MT22"]
    assert all(r["seed"] == 9 and r["purpose"] for r in rows)


def test_the_seed_and_the_defaults_change_the_run_id() -> None:
    def identity(seed: int, settings: dict) -> str:
        return run_id([], [], {"tier_b": settings}, "1.1.0")

    base = registry.settings()
    assert base["seed"] == 1 and base["methods"]["MT11"]["n_simulations"] == 10_000
    assert identity(1, base) == identity(1, registry.settings())
    assert identity(1, base) != identity(2, registry.settings(seed=2))
    changed = registry.settings()
    changed["methods"]["MT14"]["extension_periods"] = 50
    assert identity(1, changed) != identity(1, base)


def test_streams_per_group_are_stable_and_independent_of_order() -> None:
    a = generator(5, "NON_LIFE", "MOTOR_OD").random(3)
    b = generator(5, "NON_LIFE", "MOTOR_OD").random(3)
    other = generator(5, "NON_LIFE", "MOTOR_TPL").random(3)
    np.testing.assert_array_equal(a, b)
    assert not np.array_equal(a, other)
    np.testing.assert_array_equal(generator(5).random(3), np.random.default_rng(5).random(3))
    assert key_words("a", "bc") != key_words("ab", "c")
    with pytest.raises(ValueError, match="whole number"):
        generator(-1)


def test_every_judgement_has_an_entry_in_force_with_its_default() -> None:
    register = AssumptionsRegister()
    for method, rows in PARAMETERS.items():
        values, entries = parameters(method, "NON_LIFE/MOTOR_OD/paid", register)
        assert [e.name for e in entries] == [p.name for p in rows]
        assert all(e.is_default and e.why for e in entries)
        assert values == {p.name: p.default for p in rows}
    assert horizons(PARAMETERS["MT22"][0].default) == (12, 24, 36)


def _entry(method: str, name: str, value: object, target: str = "") -> Assumption:
    return Assumption(method=method, name=name, value=value, target=target, who="owner",  # type: ignore[arg-type]
                      when=date(2026, 10, 25), why="reviewed with the claims team")  # fmt: skip


def test_user_entries_replace_defaults_and_are_checked() -> None:
    register = AssumptionsRegister(
        entries=(_entry("MT13", "iterations", 2), _entry("MT13", "prior", "MT04"),
                 _entry("MT11", "process_distribution", "odp"),
                 _entry("MT22", "horizons_months", "12, 24"))
    )  # fmt: skip
    values, entries = parameters("MT13", "S", register)
    assert values["iterations"] == 2 and values["prior"] == "MT04"
    chosen = {e.name: e for e in entries}
    assert chosen["iterations"].who == "owner" and chosen["iterations"].default == 1
    assert parameters("MT11", "S", register)[0]["process_distribution"] == "odp"
    assert horizons(parameters("MT22", "S", register)[0]["horizons_months"]) == (12, 24)
    for bad, message in (
        (_entry("MT13", "iterations", 1.5), "whole number"),
        (_entry("MT13", "iterations", -1), "below"),
        (_entry("MT13", "prior", "MT05"), "allowed"),
        (_entry("MT11", "centre_residuals", "yes"), "true or false"),
        (_entry("MT13", "iterations", "two"), "not a number"),
        (_entry("MT22", "horizons_months", "a year"), "whole months"),
        (_entry("MT13", "iterations", 2, target="2021"), "whole scope"),
        (_entry("MT15", "future_index", "assumption"), "future_rate"),
    ):
        method = bad.method
        with pytest.raises(AssumptionError, match=message):
            parameters(method, "S", AssumptionsRegister(entries=(bad,)))
