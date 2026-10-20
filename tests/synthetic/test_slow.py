"""Slow checks: statistical recovery of the parameters on `medium`, and files written to disk."""

from datetime import date
from pathlib import Path

import numpy as np
import polars as pl
import pytest
import yaml

from actuarycanary.synthetic.build import Simulation, simulate, synthesize
from actuarycanary.synthetic.check import check_folder
from actuarycanary.synthetic.claims import REGULAR, Cumulative
from actuarycanary.synthetic.days import to_day
from actuarycanary.synthetic.scenario import list_scenarios
from tests.synthetic.conftest import FIXTURES
from tests.synthetic.test_files import expected_violations

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def medium() -> Simulation:
    return simulate("baseline", "medium")


def test_claim_frequency_per_line_lands_near_its_parameter(medium):
    table = medium.truth["frequency_severity"]
    for line, group in table.group_by("line"):
        expected = group["expected_frequency"][0]
        claims, exposure = group["claims_regular"].sum(), group["exposure_years"].sum()
        sigma = np.sqrt(claims) / exposure  # a Poisson count
        assert abs(claims / exposure - expected) < 4 * sigma, line


def test_mean_severity_of_own_damage_lands_near_its_parameter(medium):
    w = medium.world
    keep = (w.c_line == "MOTOR_OD") & (w.c_kind == REGULAR) & ~w.c_nil
    sample = w.c_cost[keep]
    expected = medium.truth["frequency_severity"].filter(pl.col("line") == "MOTOR_OD")[
        "expected_base_severity"
    ][0]
    assert abs(sample.mean() - expected) < 4 * sample.std() / np.sqrt(len(sample))


def test_share_of_nil_closures_and_reopenings_land_near_their_parameters(medium):
    w = medium.world
    for line, spec in medium.scenario.lines.items():
        mine = w.c_line == line
        n = int(mine.sum())
        nil = w.c_nil[mine].mean()
        assert abs(nil - spec.nil_close_probability) < 4 * np.sqrt(
            spec.nil_close_probability / n
        ), line
        live = mine & ~w.c_nil
        reopened = w.has_reopen[live].mean()
        sigma = np.sqrt(max(spec.reopen_probability, 1e-4) / live.sum())
        assert abs(reopened - spec.reopen_probability) < 4 * sigma, line


def test_cancellation_share_lands_near_its_parameter(medium):
    p = medium.policies
    started = p.start < to_day(
        date(2024, 1, 1)
    )  # their cancellations are all visible by the cut-off
    for line, spec in medium.scenario.lines.items():
        mine = started & (p.line == line)
        share = (p.cancel[mine] != np.iinfo(np.int64).max).mean()
        probability = spec.portfolio.cancellation_probability
        assert abs(share - probability) < 4 * np.sqrt(probability / mine.sum()), line


def test_reporting_delay_median_lands_near_its_parameter(medium):
    w = medium.world
    mine = (w.c_line == "MOTOR_OD") & (w.c_kind == REGULAR)
    assert np.median(w.c_rep[mine] - w.c_occ[mine]) == pytest.approx(5, abs=1)


def test_case_reserve_bias_lands_near_its_parameter_in_each_regime(medium):
    w = medium.world
    cum = Cumulative(w.p_claim, w.p_day, w.p_w).at(w.r_claim, w.r_day)[0]
    eligible = ~w.c_nil[w.r_claim] & ~w.has_reopen[w.r_claim]
    truth = w.c_cost[w.r_claim] * w.index_for(w.r_claim, w.r_day) * np.maximum(1.0 - cum, 1e-12)
    ratio = w.r_estimate / truth
    day = w.r_day
    own = eligible & (w.c_line[w.r_claim] == "MOTOR_OD")
    assert ratio[own].mean() == pytest.approx(1.05, abs=0.03)
    tpl = eligible & (w.c_line[w.r_claim] == "MOTOR_TPL")
    switch = to_day(date(2022, 1, 1))
    assert ratio[tpl & (day < switch)].mean() == pytest.approx(0.90, abs=0.04)
    assert ratio[tpl & (day >= switch)].mean() == pytest.approx(1.15, abs=0.04)


def test_realised_price_index_follows_the_chosen_path(medium):
    path = medium.truth["inflation"].filter(pl.col("month_end").dt.month() == 12)
    rates = medium.scenario.market.cpi.annual_rate_by_year
    for row in path.iter_rows(named=True):
        year = row["month_end"].year
        if row["cpi_year_on_year"] is not None and year in rates:
            assert row["cpi_year_on_year"] == pytest.approx(rates[year], abs=0.07), year


def test_baseline_loss_ratios_are_plausible_at_the_start(medium):
    u = medium.truth["ultimates"].filter(
        (pl.col("currency") == "TRY") & (pl.col("accident_year") == 2016)
    )
    by_line = u.group_by("line").agg(pl.col("ultimate_gross").sum(), pl.col("earned_premium").sum())
    ratios = {
        r["line"]: r["ultimate_gross"] / r["earned_premium"] for r in by_line.iter_rows(named=True)
    }
    assert 0.3 < ratios["MOTOR_OD"] < 0.8 and 0.3 < ratios["GROUP_TERM_LIFE"] < 1.0


def test_the_same_seed_writes_the_same_bytes(tmp_path: Path):
    first, second = tmp_path / "a", tmp_path / "b"
    synthesize("baseline", "tiny", first)
    synthesize("baseline", "tiny", second)
    names = sorted(p.relative_to(first).as_posix() for p in first.rglob("*") if p.is_file())
    assert names == sorted(
        p.relative_to(second).as_posix() for p in second.rglob("*") if p.is_file()
    )
    for name in names:
        assert (first / name).read_bytes() == (second / name).read_bytes(), name


@pytest.mark.parametrize("scenario", ["baseline", "messy_headers"])
def test_the_committed_fixtures_are_what_the_generator_writes_today(scenario, tmp_path: Path):
    manifest = synthesize(scenario, "tiny", tmp_path)
    committed = yaml.safe_load((FIXTURES / scenario / "manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["sha256"] == committed["sha256"], (
        "run `just synth-fixtures` and commit the result"
    )


@pytest.mark.parametrize("scenario", list_scenarios())
def test_every_scenario_writes_files_that_break_only_the_injected_rules(scenario, tmp_path: Path):
    synthesize(scenario, "tiny", tmp_path)
    found: dict[str, int] = {}
    for violation in check_folder(tmp_path):
        found[violation.rule] = found.get(violation.rule, 0) + violation.count
    assert found == expected_violations(tmp_path)
