"""MT19 survival analysis: curves and percentiles by group, the Cox model of a segment, the failure
modes of the specification, the diagnostics, time units and the register entries.

Spec IDs proved: MT19.
"""

import math
from datetime import date
from typing import Any

import numpy as np
import polars as pl
import pytest

from actuarycanary.methods.assumptions import Assumption, AssumptionError, AssumptionsRegister
from actuarycanary.methods.survival import analysis as an
from actuarycanary.methods.survival import kaplan_meier, mt19_judged, survival_analysis
from tests.methods.survival.helpers import durations_frame, weibull_sample


def _two_lines(n: int = 400, seed: int = 4, ratio: float = 2.0, **frame_options):
    rng = np.random.default_rng(seed)
    line = np.where(rng.random(n) < 0.5, "FAST", "SLOW")
    time = rng.exponential(np.where(line == "FAST", 1.0, ratio) * 30.0)
    event = rng.random(n) < 0.9
    return durations_frame(time, event, line=line, **frame_options)


def test_curves_and_percentiles_equal_the_direct_estimate_for_every_group() -> None:
    frame = _two_lines()
    result = survival_analysis(frame)
    for line in ("FAST", "SLOW"):
        part = frame.filter(pl.col("line") == line)
        curve = kaplan_meier(part["duration_days"].to_numpy(), part["event"].to_numpy())
        rows = result.curves.filter((pl.col("grouping") == "line") & (pl.col("group") == line))
        assert rows["time"].to_list() == list(curve.time)
        assert np.allclose(rows["survival"].to_numpy(), curve.survival, rtol=1e-14)
        assert np.allclose(rows["lower"].to_numpy(), curve.lower, rtol=1e-14, equal_nan=True)
        median = result.percentiles.filter(
            (pl.col("grouping") == "line")
            & (pl.col("group") == line)
            & (pl.col("percentile") == 0.5)
        ).row(0, named=True)
        assert median["time"] == float(curve.time[np.flatnonzero(curve.survival <= 0.5 + 1e-12)[0]])
        assert median["lower"] <= median["time"] <= median["upper"]
    assert set(result.percentiles["percentile"].to_list()) == {0.25, 0.5, 0.75}


def test_groups_cover_all_claims_line_report_year_and_the_descriptive_class() -> None:
    frame = _two_lines(year=[2023, 2024] * 200, cutoff_class=["ATTRITIONAL", "LARGE"] * 200)
    result = survival_analysis(frame)
    groupings = set(result.groups["grouping"].to_list())
    assert groupings == {"all", "line", "report_year", an.DESCRIPTIVE_GROUPING}
    descriptive = result.groups.filter(pl.col("grouping") == an.DESCRIPTIVE_GROUPING)
    assert descriptive["descriptive"].all() and "(descriptive)" in an.DESCRIPTIVE_GROUPING
    assert not result.groups.filter(pl.col("grouping") != an.DESCRIPTIVE_GROUPING)[
        "descriptive"
    ].any()
    everything = result.groups.filter(pl.col("grouping") == "all").row(0, named=True)
    assert everything["claims"] == 400 and everything["events"] + everything["censored"] == 400
    assert everything["share_censored"] == pytest.approx(everything["censored"] / 400)


def test_the_size_class_at_the_cut_off_is_never_a_covariate() -> None:
    with pytest.raises(ValueError, match="allowed"):
        survival_analysis(_two_lines(), covariates=("size_class_at_cutoff",))
    with pytest.raises(AssumptionError, match="names separated by commas"):
        mt19_judged(
            AssumptionsRegister(entries=(_entry("covariates", "size_class_at_cutoff"),)),
            "S/survival",
        )


def test_a_curve_is_shown_for_a_group_with_few_events_with_a_thin_evidence_warning() -> None:
    rng = np.random.default_rng(2)
    n = 120
    line = np.array(["BIG"] * 100 + ["TINY"] * 20)
    event = np.array([True] * 100 + [True] * 10 + [False] * 10)
    frame = durations_frame(rng.exponential(30.0, n), event, line=line)
    result = survival_analysis(frame)
    thin = result.groups.filter(pl.col("status") == "thin evidence")
    assert thin.filter(pl.col("group") == "TINY").height == 1
    assert result.curves.filter(pl.col("group") == "TINY").height > 0  # still shown
    warnings = [d for d in result.diagnostics if d.code == "THIN_EVIDENCE"]
    assert any("TINY" in d.target and d.severity == "WARNING" for d in warnings)
    assert not any("BIG" in d.target for d in warnings)


def test_no_cox_model_for_a_segment_with_fewer_than_twenty_events() -> None:
    frame = durations_frame(
        np.arange(1.0, 31.0),
        np.array([True] * 19 + [False] * 11),
        line=["A", "B"] * 15,
    )
    result = survival_analysis(frame)
    model = result.models.row(0, named=True)
    assert model["status"] == an.NOT_RUN and "fewer than 20 events (19)" in model["reason"]
    assert result.coefficients.height == 0 and result.proportional_hazards.height == 0
    assert any(d.code == "NO_COX_MODEL" for d in result.diagnostics)
    assert result.curves.height > 0  # the curves are still made


def test_a_level_without_events_is_merged_into_the_reference_level() -> None:
    rng = np.random.default_rng(9)
    n = 300
    line = np.array(["A"] * 120 + ["B"] * 120 + ["DEAD"] * 60)
    event = np.where(line == "DEAD", False, rng.random(n) < 0.9)
    frame = durations_frame(rng.exponential(np.where(line == "B", 60.0, 30.0)), event, line=line)
    result = survival_analysis(frame)
    model = result.models.row(0, named=True)
    assert model["status"] == an.RUN
    assert "level DEAD has no events and is merged into the reference level" in model["note"]
    assert result.coefficients["term"].to_list() == [f"line={x}" for x in _non_reference(result)]
    assert "line=DEAD" not in result.coefficients["term"].to_list()


def _non_reference(result: an.Survival) -> list[str]:
    reference = result.coefficients["reference"][0]
    return [x for x in ("A", "B") if x != reference]


def test_the_reference_level_is_the_one_with_the_most_events() -> None:
    frame = _two_lines(n=500)
    result = survival_analysis(frame)
    events = {
        line: int(frame.filter(pl.col("line") == line)["event"].sum()) for line in ("FAST", "SLOW")
    }
    expected = max(events, key=lambda k: events[k])
    assert set(result.coefficients["reference"].to_list()) == {expected}


def test_a_covariate_with_one_level_is_not_used_and_with_nothing_left_no_model_runs() -> None:
    frame = durations_frame(np.random.default_rng(0).exponential(30.0, 100), np.ones(100, bool))
    result = survival_analysis(frame)  # one line
    model = result.models.row(0, named=True)
    assert model["status"] == an.NOT_RUN and "no covariate varies" in model["reason"]
    assert "one level (L)" in model["note"]


def test_a_model_that_does_not_converge_is_not_run_with_the_reason() -> None:
    time = np.arange(1.0, 61.0)
    frame = durations_frame(time, np.ones(60, bool), line=np.where(time <= 30, "EARLY", "LATE"))
    result = survival_analysis(frame)
    model = result.models.row(0, named=True)
    assert model["status"] == an.NOT_RUN
    assert "without bound" in model["reason"] or "converge" in model["reason"]
    assert any(
        d.code == "NO_COX_MODEL" and model["reason"] in d.message for d in result.diagnostics
    )


def test_the_cox_model_recovers_a_known_hazard_ratio_and_flags_nothing_when_proportional() -> None:
    rng = np.random.default_rng(31)
    time, event, x = weibull_sample(rng, 3000, np.array([0.7]), shape=1.5)
    frame = durations_frame(time * 100.0, event, line=np.where(x[:, 0] == 1.0, "B", "A"))
    result = survival_analysis(frame, ties="breslow")
    row = result.coefficients.row(0, named=True)
    # B has the higher hazard; the reference is the level with the more events, so the term is
    # either B against A (+0.7) or A against B (-0.7)
    sign = 1.0 if row["term"] == "line=B" else -1.0
    assert row["coefficient"] == pytest.approx(sign * 0.7, abs=0.15)
    truth = math.exp(sign * 0.7)
    assert row["hazard_ratio_lower"] < truth < row["hazard_ratio_upper"]
    level = row["term"].split("=")[1]
    assert row["events"] == int(frame.filter(pl.col("line") == level)["event"].sum())
    model = result.models.row(0, named=True)
    assert model["ties"] == "breslow" and model["likelihood_ratio"] > 0 and model["df"] == 1
    assert 0.5 < model["concordance"] < 1.0
    ph = result.proportional_hazards
    assert ph["term"].to_list() == [row["term"], "GLOBAL"]
    assert not any(d.code == "NON_PROPORTIONAL_HAZARDS" for d in result.diagnostics)


def test_crossing_hazards_raise_the_proportional_hazards_warning() -> None:
    rng = np.random.default_rng(6)
    n = 2000
    flag = rng.integers(0, 2, n)
    time = np.where(flag == 1, rng.weibull(0.6, n), rng.weibull(2.5, n)) * 100.0
    frame = durations_frame(time, np.ones(n, bool), line=np.where(flag == 1, "B", "A"))
    codes = {d.code for d in survival_analysis(frame).diagnostics}
    assert "NON_PROPORTIONAL_HAZARDS" in codes


def test_several_covariates_make_one_term_per_non_reference_level() -> None:
    rng = np.random.default_rng(12)
    n = 800
    line = rng.choice(["A", "B", "C"], n)
    cause = rng.choice(["X", "Y"], n)
    frame = durations_frame(rng.exponential(30.0, n), rng.random(n) < 0.9, line=line, cause=cause)
    result = survival_analysis(frame, covariates=("line", "cause"))
    assert result.models["covariates"][0] == "line, cause"
    assert set(result.coefficients["covariate"].to_list()) == {"line", "cause"}
    assert result.coefficients.height == 3  # two lines and one cause besides the references
    assert "cause" in set(result.groups["grouping"].to_list())  # curves by every covariate
    assert result.proportional_hazards.height == 4  # three terms and the global test
    assert result.baseline["group"].n_unique() <= an.BASELINE_GROUPS


def test_the_size_class_at_report_is_a_covariate() -> None:
    rng = np.random.default_rng(15)
    n = 600
    klass = rng.choice(["ATTRITIONAL", "LARGE"], n, p=[0.8, 0.2])
    time = rng.exponential(np.where(klass == "LARGE", 90.0, 30.0))
    frame = durations_frame(time, rng.random(n) < 0.9, size_class=klass)
    result = survival_analysis(frame, covariates=("size_class_at_report",))
    row = result.coefficients.row(0, named=True)
    assert row["term"] == "size_class_at_report=LARGE" and row["coefficient"] < 0


def test_time_unit_scales_the_curves_and_leaves_the_hazard_ratios_alone() -> None:
    frame = _two_lines()
    days = survival_analysis(frame)
    months = survival_analysis(frame, time_unit="months")
    years = survival_analysis(frame, time_unit="years")
    key = (pl.col("grouping") == "all") & (pl.col("percentile") == 0.5)
    median_days = days.percentiles.filter(key)["time"][0]
    assert months.percentiles.filter(key)["time"][0] == pytest.approx(median_days / (365.25 / 12))
    assert years.percentiles.filter(key)["time"][0] == pytest.approx(median_days / 365.25)
    assert months.coefficients["coefficient"][0] == pytest.approx(
        days.coefficients["coefficient"][0], rel=1e-8
    )


def test_a_wider_confidence_widens_the_curve_interval() -> None:
    frame = _two_lines()
    narrow = survival_analysis(frame, confidence=0.8).curves.filter(pl.col("grouping") == "all")
    wide = survival_analysis(frame, confidence=0.99).curves.filter(pl.col("grouping") == "all")
    assert (wide["upper"] - wide["lower"]).sum() > (narrow["upper"] - narrow["lower"]).sum()


def test_report_years_are_compared_and_unequal_handling_speeds_are_flagged() -> None:
    rng = np.random.default_rng(14)
    n = 1200
    year = np.repeat([2022, 2023], n // 2)
    time = rng.exponential(np.where(year == 2022, 30.0, 60.0))
    frame = durations_frame(time, rng.random(n) < 0.9, year=year)
    result = survival_analysis(frame)
    cohorts = result.cohorts
    assert cohorts["report_year"].to_list() == ["2022", "2023"]
    assert cohorts["logrank_p"][0] < 1e-6 and cohorts["logrank_df"][0] == 1
    assert "COHORTS_DIFFER" in {d.code for d in result.diagnostics}
    same = survival_analysis(durations_frame(rng.exponential(30.0, n), np.ones(n, bool), year=year))
    assert "COHORTS_DIFFER" not in {d.code for d in same.diagnostics}


def test_the_share_censored_of_each_report_year_is_listed() -> None:
    frame = durations_frame(
        np.arange(1.0, 41.0),
        np.array([True] * 20 + [True] * 10 + [False] * 10),
        year=[2023] * 20 + [2024] * 20,
    )
    cohorts = survival_analysis(frame).cohorts
    assert cohorts["share_censored"].to_list() == [0.0, 0.5]


def test_the_output_curve_keeps_the_exact_points_and_at_most_the_row_limit() -> None:
    rng = np.random.default_rng(1)
    n = 3000
    frame = durations_frame(rng.exponential(300.0, n).round(), np.ones(n, bool))
    curve = survival_analysis(frame).curves.filter(pl.col("grouping") == "all")
    assert curve.height <= an.CURVE_ROWS
    direct = kaplan_meier(frame["duration_days"].to_numpy(), frame["event"].to_numpy())
    index = np.searchsorted(direct.time, curve["time"].to_numpy())
    assert np.allclose(curve["survival"].to_numpy(), direct.survival[index], rtol=1e-14)
    assert curve["time"][0] == direct.time[0] and curve["time"][-1] == direct.time[-1]


def test_month_end_dates_are_counted_in_the_groups_table() -> None:
    frame = durations_frame(
        np.arange(1.0, 31.0), np.ones(30, bool), approximate=[True] * 10 + [False] * 20
    )
    assert (
        survival_analysis(frame).groups.filter(pl.col("grouping") == "all")["month_end_dates"][0]
        == 10
    )


def test_every_segment_is_analysed_on_its_own() -> None:
    a = durations_frame(np.arange(1.0, 41.0), np.ones(40, bool), segment="A")
    b = durations_frame(np.arange(1.0, 41.0) * 2, np.ones(40, bool), segment="B")
    result = survival_analysis(pl.concat([a, b]))
    assert result.models["segment"].to_list() == ["A", "B"]
    medians = result.percentiles.filter(
        (pl.col("grouping") == "all") & (pl.col("percentile") == 0.5)
    )
    assert medians.sort("segment")["time"].to_list() == [20.0, 40.0]


def test_unknown_options_are_refused() -> None:
    frame = _two_lines(n=60)
    wrong: list[dict[str, Any]] = [
        {"ties": "exact"},
        {"time_unit": "weeks"},
        {"confidence": 1.2},
        {"covariates": ("colour",)},
    ]
    for options in wrong:
        with pytest.raises(ValueError):
            survival_analysis(frame, **options)
    with pytest.raises(ValueError, match="needs a column"):
        survival_analysis(frame.drop("event"))


def test_claims_with_a_negative_or_missing_duration_are_left_out() -> None:
    frame = durations_frame(np.array([5.0, -1.0, 7.0, 9.0]), np.ones(4, bool))
    frame = frame.with_columns(pl.Series("duration_days", [5.0, -1.0, None, 9.0], dtype=pl.Float64))
    assert survival_analysis(frame).groups.filter(pl.col("grouping") == "all")["claims"][0] == 2


# ------------------------------------------------------------------ the register


def _entry(name: str, value, who: str = "analyst") -> Assumption:
    return Assumption(
        method="MT19", name=name, scope="S/survival", value=value, who=who,
        when=date(2026, 10, 27), why="test",
    )  # fmt: skip


def test_defaults_come_back_as_entries_in_force() -> None:
    options, entries = mt19_judged(AssumptionsRegister(), "S/survival")
    assert options == {
        "event": "closed",
        "covariates": ("line",),
        "ties": "efron",
        "confidence": 0.95,
        "time_unit": "days",
    }
    assert [e.name for e in entries] == ["event", "covariates", "ties", "confidence", "time_unit"]
    assert all(e.is_default and e.method == "MT19" and e.scope == "S/survival" for e in entries)
    assert [e.value for e in entries] == ["closed", "line", "efron", 0.95, "days"]


def test_a_user_entry_replaces_the_default_for_its_scope_only() -> None:
    register = AssumptionsRegister(
        entries=(
            _entry("ties", "breslow"),
            _entry("covariates", "line, cause"),
            _entry("event", "closed_with_payment"),
            _entry("confidence", 0.9),
            _entry("time_unit", "months"),
        )
    )
    options, entries = mt19_judged(register, "S/survival")
    assert options["ties"] == "breslow" and options["covariates"] == ("line", "cause")
    assert options["event"] == "closed_with_payment" and options["confidence"] == 0.9
    assert options["time_unit"] == "months"
    by_name = {e.name: e for e in entries}
    assert by_name["ties"].who == "analyst" and by_name["ties"].default == "efron"
    assert by_name["covariates"].value == "line, cause" and by_name["covariates"].default == "line"
    other, _ = mt19_judged(register, "T/survival")
    assert other["ties"] == "efron"  # another segment keeps the default


def test_a_value_the_caller_passes_is_a_run_setting() -> None:
    _, entries = mt19_judged(AssumptionsRegister(), "S/survival", ties="breslow")
    ties = next(e for e in entries if e.name == "ties")
    assert ties.value == "breslow" and ties.who == "run settings" and ties.default == "efron"


@pytest.mark.parametrize(
    "name,value",
    [
        ("ties", "exact"),
        ("event", "paid"),
        ("covariates", "colour"),
        ("covariates", " , "),
        ("confidence", 1.5),
        ("confidence", "high"),
        ("time_unit", "weeks"),
    ],
)
def test_a_malformed_entry_is_refused(name: str, value) -> None:
    with pytest.raises(AssumptionError):
        mt19_judged(AssumptionsRegister(entries=(_entry(name, value),)), "S/survival")


def test_an_entry_for_a_target_is_refused() -> None:
    entry = Assumption(
        method="MT19", name="ties", scope="S/survival", target="x", value="breslow",
        who="analyst", why="test",
    )  # fmt: skip
    with pytest.raises(AssumptionError, match="whole scope"):
        mt19_judged(AssumptionsRegister(entries=(entry,)), "S/survival")
