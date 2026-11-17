"""Exposure and decrements (CV11, records 0445 to 0447): hand cases, the generator's truth on the
tiny life book, the pipeline's helper and the line of the data page."""

from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from actuarycanary.canonical.feeds import CanonicalFeed
from actuarycanary.canonical.life import AGE_HIGH, AGE_LOW, parse_age_band
from actuarycanary.life.exposure import Exposure, exposure, study_period
from actuarycanary.life.settings import LifeSettings
from actuarycanary.pipeline import _life_exposure
from actuarycanary.report.model import _life_line
from tests.quality.builders import frames
from tests.report.scope_guard import check

Y = 365.25
CUT = date(2024, 12, 31)
NO_LAG = LifeSettings(reporting_lag_months=0, age_band_width=1)


def lif(contract: str = "L1", year: int = 2022, age: str = "47", **values: Any):
    return {
        "contract_id": contract,
        "valuation_date": date(year, 12, 31),
        "product": "TERM",
        "entry_date": date(2020, 7, 1),
        "age_band": age,
        "status": "IN_FORCE",
        "segment": "LIFE",
        "line": "TERM_LIFE",
        "sum_assured": 1000.0,
        **values,
    }


def lev(kind: str, day: date, contract: str = "L1"):
    return {
        "event_id": f"{contract}{day}{kind}",
        "contract_id": contract,
        "event_date": day,
        "event_type": kind,
    }


def _frames(in_force: list, events: list | None = None):
    rows = {"life_in_force": in_force, **({"life_events": events} if events is not None else {})}
    built = frames(rows)
    low, high, _ = parse_age_band(pl.col("age_band"))
    lif_frame = built["life_in_force"].with_columns(low.alias(AGE_LOW), high.alias(AGE_HIGH))
    return lif_frame, built.get("life_events")


def run(in_force: list, events: list | None = None, cut: date = CUT, settings=NO_LAG):
    lif_frame, lev_frame = _frames(in_force, events)
    return exposure(lif_frame, lev_frame, cut, settings)


def cell(result: Exposure, year: int, age: int) -> dict[str, Any]:
    rows = result.cells.filter((pl.col(result.period_column) == year) & (pl.col("age") == age))
    assert rows.height == 1, rows
    return rows.row(0, named=True)


BOOK = [lif(year=2022, age="47"), lif(year=2023, age="48"), lif(year=2024, age="49")]


def test_an_anniversary_inside_a_year_splits_the_year_into_two_cells() -> None:
    result = run(BOOK)
    # entry 2020-07-01, 47 at 2022-12-31: entry age 45; 46 until 2022-07-01, then 47
    first, second = cell(result, 2022, 46), cell(result, 2022, 47)
    assert first["policy_year"] == 2 and second["policy_year"] == 3
    assert first["central_exposure"] == pytest.approx(181 / Y, abs=1e-12)
    assert second["central_exposure"] == pytest.approx(184 / Y, abs=1e-12)
    total = result.cells["central_exposure"].sum()
    assert total == pytest.approx((date(2025, 1, 1) - date(2022, 1, 1)).days / Y, abs=1e-12)
    assert result.study == study_period(date(2022, 12, 31), CUT, 0)
    assert result.exits_by_events == result.exits_by_half_interval == 0


def test_a_lapse_ends_exposure_and_is_counted_in_its_cell_with_its_initial_exposure() -> None:
    in_force = [*BOOK[:1], lif(year=2023, age="48", status="LAPSED")]
    result = run(in_force, [lev("LAPSE", date(2023, 3, 10))])
    lapsed = cell(result, 2023, 47)
    assert lapsed["central_exposure"] == pytest.approx(68 / Y, abs=1e-12)  # 1 Jan to 10 Mar
    assert lapsed["lapses"] == 1 and lapsed["deaths"] == 0
    # initial exposure adds the time to the end of the age year (1 July 2023)
    assert lapsed["initial_exposure_lapse"] == pytest.approx((68 + 113) / Y, abs=1e-12)
    assert lapsed["initial_exposure_mortality"] == pytest.approx(68 / Y, abs=1e-12)
    assert result.cells.filter(pl.col("calendar_year") == 2024).height == 0
    assert result.exits_by_events == 1


def test_a_reinstatement_opens_a_new_spell() -> None:
    events = [lev("LAPSE", date(2023, 3, 10)), lev("REINSTATEMENT", date(2023, 6, 1))]
    result = run(BOOK, events)
    gap = (date(2023, 6, 1) - date(2023, 3, 10)).days
    total = (date(2025, 1, 1) - date(2022, 1, 1)).days - gap
    assert result.cells["central_exposure"].sum() == pytest.approx(total / Y, abs=1e-12)
    assert result.cells["lapses"].sum() == 1


def test_only_the_earliest_terminal_event_of_a_spell_counts() -> None:
    events = [lev("LAPSE", date(2023, 3, 10)), lev("SURRENDER", date(2023, 4, 1))]
    result = run(BOOK, events)
    assert (result.cells["lapses"].sum(), result.cells["surrenders"].sum()) == (1, 0)


def test_without_an_event_the_exit_is_dated_at_the_middle_of_the_interval() -> None:
    in_force = [*BOOK[:1], lif(year=2023, age="48", status="DEATH_CLAIM"), lif(year=2024, age="49")]
    result = run(in_force)  # no life_events; the 2024 row after the exit is ignored (DV-LIF-08)
    exit_day = date(2023, 7, 1)  # 2022-12-31 + 365 // 2 days, the anniversary itself
    assert result.exits_by_half_interval == 1
    assert result.cells["deaths"].sum() == 1
    total = (exit_day - date(2022, 1, 1)).days
    assert result.cells["central_exposure"].sum() == pytest.approx(total / Y, abs=1e-12)
    died = cell(result, 2023, 48)  # dated on the anniversary: the new age year
    assert died["deaths"] == 1 and died["sum_assured_deaths"] == 1000.0


def test_the_reporting_lag_leaves_the_last_months_out_of_mortality_only() -> None:
    settings = LifeSettings(reporting_lag_months=3, age_band_width=1)
    events = [lev("DEATH", date(2024, 11, 1)), lev("LAPSE", date(2024, 11, 2), "L2")]
    in_force = [*BOOK, *(lif("L2", y, str(30 + y - 2022)) for y in (2022, 2023, 2024))]
    result = run(in_force, events, settings=settings)
    assert result.study.mortality_end == date(2024, 9, 30)
    assert (result.cells["deaths"].sum(), result.cells["lapses"].sum()) == (0, 1)
    mortality = result.cells["central_exposure_mortality"].sum()
    assert mortality == pytest.approx(2 * (date(2024, 10, 1) - date(2022, 1, 1)).days / Y)
    lapse_view = result.cells["central_exposure"].sum()
    expected = (date(2024, 11, 1) - date(2022, 1, 1)).days + (
        date(2024, 11, 2) - date(2022, 1, 1)
    ).days
    assert lapse_view == pytest.approx(expected / Y)


def test_the_study_ends_with_the_last_whole_calendar_year() -> None:
    study = study_period(date(2022, 12, 31), date(2024, 6, 30), 3)
    assert (study.start, study.end, study.mortality_end) == (
        date(2022, 1, 1),
        date(2023, 12, 31),
        date(2023, 12, 31),
    )
    assert study_period(date(2022, 1, 31), date(2024, 12, 31), 3).mortality_end == date(2024, 9, 30)


def test_policy_year_cells_are_not_cut_at_the_first_of_january() -> None:
    settings = LifeSettings(study_cells="policy_year", reporting_lag_months=0, age_band_width=1)
    result = run(BOOK, settings=settings)
    assert (
        result.period_column == "anniversary_year" and "calendar_year" not in result.cells.columns
    )
    whole = cell(result, 2022, 47)  # policy year 3 begins on 2022-07-01 and runs a whole year
    assert whole["central_exposure"] == pytest.approx(365 / Y, abs=1e-12)


def test_amounts_are_weighted_by_the_value_at_the_start_of_the_cell() -> None:
    in_force = [lif(year=2022, sum_assured=1000.0), lif(year=2023, age="48", sum_assured=3000.0)]
    result = run(in_force, cut=date(2023, 12, 31))
    early, late = cell(result, 2022, 46), cell(result, 2023, 47)
    # the 2022 cells start before the first valuation: its value is used
    assert early["sum_assured_exposure"] == pytest.approx(1000.0 * 181 / Y)
    assert late["sum_assured_exposure"] == pytest.approx(1000.0 * 181 / Y)  # 2022-12-31 value
    assert cell(result, 2023, 48)["sum_assured_exposure"] == pytest.approx(1000.0 * 184 / Y)


def test_sex_is_a_cell_key_only_when_asked() -> None:
    in_force = [lif(sex="FEMALE"), lif("L2", sex="MALE")]
    plain = run(in_force, cut=date(2022, 12, 31))
    assert "sex" not in plain.cells.columns
    settings = LifeSettings(use_sex=True, reporting_lag_months=0, age_band_width=1)
    by_sex = run(in_force, cut=date(2022, 12, 31), settings=settings)
    assert set(by_sex.cells["sex"]) == {"FEMALE", "MALE"}


# --- the generator's truth ------------------------------------------------------------------

KEYS = ["calendar_year", "product", "age", "policy_year"]


@pytest.fixture(scope="module")
def life_truth(scenario_folder, scenario_checked):
    feeds, _ = scenario_checked("life_book")
    result = exposure(
        feeds["life_in_force"].frame, feeds["life_events"].frame, date(2025, 12, 31), NO_LAG
    )
    truth = pl.read_csv(scenario_folder("life_book") / "truth" / "life_expected_decrements.csv")
    mine = result.cells.group_by(KEYS).agg(
        pl.col("central_exposure", "deaths").sum(),
        (pl.col("lapses") + pl.col("surrenders")).sum().alias("lapses_and_surrenders"),
    )
    return result, truth.join(mine, on=KEYS, how="full", coalesce=True).fill_null(0)


def test_exposure_and_decrements_equal_the_truth_cell_by_cell(life_truth) -> None:
    """Unbanded products: every cell of calendar year, product, age and policy year within the
    rounding of the truth file (6 decimals), deaths and lapses equal (record 0446)."""
    _, both = life_truth
    exact = both.filter(pl.col("product") != "GROUP_TERM")
    assert exact.height > 400
    gap = (exact["central_exposure"] - exact["exposure_years"]).abs().max()
    assert gap < 1e-6  # type: ignore[operator]
    assert (exact["deaths_right"] == exact["deaths_reported"]).all()
    assert (exact["lapses_and_surrenders"] == exact["lapses"]).all()


def test_a_banded_product_equals_the_truth_by_year_and_policy_year(life_truth) -> None:
    """GROUP_TERM gives ages in bands of five: its entry age is the band's lower age (CV11), so
    its cells differ by age; summed over age they equal the truth."""
    _, both = life_truth
    keys = ["calendar_year", "product", "policy_year"]
    summed = both.group_by(keys).agg(
        pl.col("central_exposure", "exposure_years", "deaths_right", "deaths_reported").sum(),
        pl.col("lapses_and_surrenders", "lapses").sum(),
    )
    assert (summed["central_exposure"] - summed["exposure_years"]).abs().max() < 1e-5  # type: ignore[operator]
    assert (summed["lapses_and_surrenders"] == summed["lapses"]).all()
    assert (summed["deaths_right"] == summed["deaths_reported"]).all()


# --- the pipeline and the data page ---------------------------------------------------------


def test_the_pipeline_computes_exposure_only_with_life_in_force(life_truth) -> None:
    result, _ = life_truth
    lif_frame, _ = _frames(BOOK)
    feed = CanonicalFeed("life_in_force", "0", lif_frame, (), ())
    assert _life_exposure({}, CUT, NO_LAG) is None
    empty = CanonicalFeed("life_in_force", "0", lif_frame.head(0), (), ())
    assert _life_exposure({"life_in_force": empty}, CUT, NO_LAG) is None
    got = _life_exposure({"life_in_force": feed}, CUT, NO_LAG)
    assert got is not None and got.cells.height > 0
    record = result.manifest_record()
    assert record["file"] == "life_exposure.csv" and record["age_definition"] == "age_last_birthday"


def test_the_data_page_names_the_life_feeds_by_segment(life_truth) -> None:
    result, _ = life_truth
    rows = _life_line(result)
    assert [r["segment"] for r in rows] == ["LIFE", "PENSION"]
    assert rows[0]["text"].startswith("Life feeds of LIFE: exposure 2022 to 2025, ")
    body = {"life": rows, "scopes": {"life": {"title": "x", "level": "segment"}}}
    assert check(body, {"LIFE", "PENSION"}, "M01") == []


def test_a_run_without_life_feeds_writes_what_it_wrote(default_run) -> None:
    assert not (default_run.folder / "life_exposure.csv").exists()
    manifest = default_run.manifest.read_text(encoding="utf-8")
    assert '"life_exposure"' not in manifest
    data = next(p for p in default_run.report_data["pages"] if p["module"] == "M01")["body"]
    assert "life" not in data and "life" not in data["scopes"]


@pytest.mark.slow  # a run of its own (conftest): the life book end to end
def test_the_life_book_end_to_end(scenario_folder, tmp_path: Path) -> None:
    """The tiny life book, its later feeds and its mortality table with a sidecar, through
    `run`: life_exposure.csv equals the exposure of the feeds, the manifest names it and the
    table, the data page has its line. (The demo scenario has no life book, record 0446.)"""
    import json
    import shutil

    from actuarycanary.pipeline import run as pipeline_run

    source, data = scenario_folder("life_book"), tmp_path / "data"
    data.mkdir()
    for path in [*source.glob("*.xlsx"), *(source / "phase2").glob("*.xlsx")]:
        shutil.copy(path, data / path.name)
    shutil.copytree(source / "reference_tables", data / "reference_tables")
    (data / "reference_tables" / "reference_mortality.yaml").write_text(
        "name: Synthetic\ndecrement: DEATH\nsource: generator\nlicence: synthetic\n"
    )
    result = pipeline_run(data, tmp_path / "out", cache_dir=None)
    manifest = json.loads(result.manifest.read_text(encoding="utf-8"))
    assert manifest["life_exposure"]["contracts"] > 0
    assert [t["file"] for t in manifest["reference_tables"]["used"]] == [
        "reference_tables/reference_mortality.csv"
    ]
    written = pl.read_csv(result.folder / "life_exposure.csv")
    assert written["central_exposure"].sum() > 0
    m01 = next(p for p in result.report_data["pages"] if p["module"] == "M01")["body"]
    assert [r["segment"] for r in m01["life"]] == ["LIFE", "PENSION"]
