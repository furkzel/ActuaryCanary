"""Exposure and decrements of the life studies (CV11, records 0445 to 0447).

A contract's time in force is split into spells: from entry (or a REINSTATEMENT) to its terminal
event. Spells are cut at every policy anniversary (age and policy year move together), at
1 January (calendar-year cells; with `study_cells: policy_year` not) and at the study boundaries.

- **Exit date**: the event_date of the contract's terminal event in life_events (the earliest of
  a spell, DV-LEV-06; a REINSTATEMENT after an exit opens a new spell). A contract without a
  terminal event whose status shows an exit is dated at the middle of the interval between the
  previous valuation (or its entry) and the first valuation with the exit status: the half-
  interval rule, counted in the output's conventions. Rows after an exit without reinstatement
  are ignored (DV-LIF-08).
- **Central exposure**: days in the cell / 365.25, half-open [start, exit).
- **Initial exposure**: central exposure plus, for each decrement of the studied type in the
  cell, the time from the event to the next anniversary (the end of its age year).
- **Study period** (0447): from 1 January of the year of the first valuation to the end of the
  last whole calendar year on or before the cut-off. Mortality columns stop
  `reporting_lag_months` before the cut-off (deaths are reported late); lapse, surrender and other
  exits use the whole period.
- **Counting**: lives (one contract, one life); amounts as a second view, the sum assured
  (mortality) and the fund value (surrender) of the latest valuation on or before the start of
  the cell (else the first valuation).
"""

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import numpy as np
import polars as pl

from actuarycanary.life.ages import band_expr, jan1, shift_years, to_days, whole_years, year_of
from actuarycanary.life.settings import LifeSettings

DAYS_PER_YEAR = 365.25
DEATH = "DEATH"
LAPSES = ("LAPSE",)
SURRENDERS = ("SURRENDER",)
OTHER_EXITS = ("MATURITY", "TRANSFER_OUT")
TERMINAL = ("DEATH", "SURRENDER", "LAPSE", "MATURITY", "TRANSFER_OUT")
REINSTATEMENT = "REINSTATEMENT"
EXIT_OF_STATUS = {
    "DEATH_CLAIM": "DEATH",
    "LAPSED": "LAPSE",
    "SURRENDERED": "SURRENDER",
    "MATURED": "MATURITY",
    "TRANSFERRED_OUT": "TRANSFER_OUT",
}
FILE_NAME = "life_exposure.csv"
MEASURES = (
    "central_exposure",
    "central_exposure_mortality",
    "initial_exposure_mortality",
    "initial_exposure_lapse",
    "deaths",
    "lapses",
    "surrenders",
    "other_exits",
    "sum_assured_exposure",
    "fund_value_exposure",
    "sum_assured_deaths",
    "fund_value_surrenders",
)


@dataclass(frozen=True)
class Study:
    start: date  # first day of the study
    end: date  # last day of the study
    mortality_end: date  # last day of the mortality columns
    cut_off: date


@dataclass(frozen=True)
class Exposure:
    cells: pl.DataFrame
    study: Study
    settings: LifeSettings
    contracts: int
    exits_by_events: int
    exits_by_half_interval: int
    events_without_contract: int

    @property
    def period_column(self) -> str:
        return (
            "calendar_year" if self.settings.study_cells == "calendar_year" else "anniversary_year"
        )

    def years(self) -> tuple[int, int] | None:
        if self.cells.height == 0:
            return None
        column = self.cells[self.period_column]
        return int(column.min()), int(column.max())  # type: ignore[arg-type]

    def manifest_record(self) -> dict[str, Any]:
        """The conventions of `life_exposure.csv` (CV11), for the manifest."""
        s = self.settings
        return {
            "file": FILE_NAME,
            "study_start": self.study.start.isoformat(),
            "study_end": self.study.end.isoformat(),
            "mortality_end": self.study.mortality_end.isoformat(),
            "cut_off": self.study.cut_off.isoformat(),
            "age_definition": s.age_definition,
            "exposure": s.exposure,
            "study_cells": s.study_cells,
            "age_band_width": s.age_band_width,
            "reporting_lag_months": s.reporting_lag_months,
            "use_sex": s.use_sex,
            "year_length_days": DAYS_PER_YEAR,
            "counting": "lives; amounts weighted by sum assured (mortality) and fund value "
            "(surrender) of the latest valuation on or before the start of the cell",
            "exit_dates": "terminal event of life_events; else the half-interval rule",
            "contracts": self.contracts,
            "exits_by_events": self.exits_by_events,
            "exits_by_half_interval": self.exits_by_half_interval,
            "events_without_contract": self.events_without_contract,
        }


def _add_months(day: date, months: int) -> date:
    """The same day of the month `months` later (earlier when negative), clamped to its end."""
    year, month = divmod(day.year * 12 + day.month - 1 + months, 12)
    return date(year, month + 1, min(day.day, monthrange(year, month + 1)[1]))


def study_period(first_valuation: date, cut_off: date, lag_months: int) -> Study:
    start = date(first_valuation.year, 1, 1)
    end = cut_off if (cut_off.month, cut_off.day) == (12, 31) else date(cut_off.year - 1, 12, 31)
    lag_end = _add_months(cut_off + timedelta(days=1), -lag_months) - timedelta(days=1)
    return Study(start, end, min(end, lag_end), cut_off)


def _contracts(in_force: pl.DataFrame, use_sex: bool) -> pl.DataFrame:
    """One row per contract: the latest valuation's terms (DV-LIF-06) and the first valuation's
    age (DV-LIF-07), with the entry age of CV11."""
    ordered = in_force.sort("contract_id", "valuation_date")
    optional = [c for c in ("segment", "line", "sex") if c in ordered.columns]
    if not use_sex and "sex" in optional:
        optional.remove("sex")
    per = ordered.group_by("contract_id", maintain_order=True).agg(
        pl.col("valuation_date").first().alias("first_valuation"),
        pl.col("age_low").first().alias("first_age"),
        pl.col("age_high").first().alias("first_age_high"),
        pl.col("product").last(),
        pl.col("entry_date").last(),
        *(pl.col(c).last() for c in optional),
    )
    if "segment" not in per.columns:
        per = per.with_columns(pl.lit(None, pl.String).alias("segment"))
    if "line" not in per.columns:
        per = per.with_columns(pl.lit(None, pl.String).alias("line"))
    if use_sex and "sex" not in per.columns:
        per = per.with_columns(pl.lit(None, pl.String).alias("sex"))
    entry, first = to_days(per["entry_date"]), to_days(per["first_valuation"])
    age = per["first_age"].to_numpy() - whole_years(entry, first)
    return per.with_columns(
        pl.col("segment").fill_null("LIFE"),  # life_in_force: an empty segment is LIFE
        pl.Series("entry_age", age, dtype=pl.Int64),
        (pl.col("first_age_high") - pl.col("first_age") + 1).fill_null(1).alias("source_width"),
        pl.col("first_age_high").is_null().alias("open_band"),
    ).with_row_index("contract")


def _effective_events(events: pl.DataFrame, contracts: pl.DataFrame) -> pl.DataFrame:
    """Terminal events and reinstatements that change the state of a contract: the first of a
    run of terminal events (DV-LEV-06) and the first reinstatement after an exit; a leading
    reinstatement changes nothing."""
    entry = contracts.select("contract_id", "contract", "entry_date")
    marks = (
        events.filter(pl.col("event_type").is_in((*TERMINAL, REINSTATEMENT)))
        .join(entry, on="contract_id")
        .filter(pl.col("event_date") >= pl.col("entry_date"))
        .sort("contract", "event_date", pl.col("event_type") == REINSTATEMENT)
        .with_columns((pl.col("event_type") == REINSTATEMENT).alias("back"))
    )
    run_start = pl.col("back") != pl.col("back").shift(1).over("contract")
    first = pl.int_range(pl.len()).over("contract") == 0
    keep = (first & ~pl.col("back")) | (~first & run_start.fill_null(True))
    return marks.filter(keep).select("contract", "event_date", "event_type", "back")


def _half_interval_exits(in_force: pl.DataFrame, contracts: pl.DataFrame, known: pl.Series):
    """Exits of contracts without a terminal event, from their statuses (CV11)."""
    ordered = (
        in_force.join(contracts.select("contract_id", "contract", "entry_date"), on="contract_id")
        .filter(~pl.col("contract").is_in(known.implode()))
        .sort("contract", "valuation_date")
        .with_columns(pl.col("valuation_date").shift(1).over("contract").alias("previous"))
    )
    first_exit = (
        ordered.filter(pl.col("status").is_in(list(EXIT_OF_STATUS)))
        .group_by("contract", maintain_order=True)
        .first()
    )
    before = pl.coalesce("previous", "entry_date").cast(pl.Int64)
    day = before + (pl.col("valuation_date").cast(pl.Int64) - before) // 2
    return first_exit.select(
        "contract",
        day.cast(pl.Date).alias("event_date"),
        pl.col("status").replace_strict(EXIT_OF_STATUS).alias("event_type"),
        pl.lit(False).alias("back"),
    )


def _spells(contracts: pl.DataFrame, marks: pl.DataFrame) -> pl.DataFrame:
    """contract, start, stop (day numbers; stop open as a large number) and exit type."""
    ordered = marks.sort("contract", "event_date").with_columns(
        pl.col("back").cast(pl.Int64).cum_sum().over("contract").alias("spell")
    )
    ends = ordered.filter(~pl.col("back")).select(
        "contract", "spell", pl.col("event_date").alias("stop"), pl.col("event_type").alias("exit")
    )
    starts = pl.concat(
        [
            contracts.select(
                "contract", pl.lit(0, pl.Int64).alias("spell"), pl.col("entry_date").alias("start")
            ),
            ordered.filter("back").select("contract", "spell", pl.col("event_date").alias("start")),
        ]
    )
    never = 1 << 40
    return starts.join(ends, on=["contract", "spell"], how="left").select(
        "contract",
        pl.col("start").cast(pl.Int64),
        pl.col("stop").cast(pl.Int64).fill_null(never),
        "exit",
    )


def _pieces(spells: pl.DataFrame, entry: np.ndarray, study: Study, calendar: bool):
    """Each spell cut at anniversaries, 1 January and the study bounds: contract, k (whole
    policy years), lo, hi (half-open, day numbers) and the period year."""
    w0 = to_days(pl.Series([study.start]))[0]
    w1 = to_days(pl.Series([study.end]))[0] + 1
    who = spells["contract"].to_numpy()
    start = np.maximum(spells["start"].to_numpy(), w0)
    stop = np.minimum(spells["stop"].to_numpy(), w1)
    live = stop > start
    who, start, stop = who[live], start[live], stop[live]
    e = entry[who]
    k = whole_years(e, start)
    parts: list[tuple[np.ndarray, ...]] = []
    while len(who):
        lo = np.maximum(start, shift_years(e, k))
        hi = np.minimum(stop, shift_years(e, k + 1))
        if calendar:
            cut = jan1(year_of(lo) + 1)
            first_hi = np.minimum(hi, cut)
            parts.append((who, k, lo, first_hi, year_of(lo)))
            more = hi > cut
            parts.append((who[more], k[more], cut[more], hi[more], year_of(cut[more])))
        else:
            parts.append((who, k, lo, hi, year_of(shift_years(e, k))))
        going = stop > hi
        who, e, start, stop, k = who[going], e[going], start[going], stop[going], k[going] + 1
    columns = ("contract", "k", "lo", "hi", "year")
    return pl.DataFrame(
        {c: np.concatenate([p[i] for p in parts]) for i, c in enumerate(columns)}
    ).filter(pl.col("hi") > pl.col("lo"))


def _value_at(
    pieces: pl.DataFrame, in_force: pl.DataFrame, contracts: pl.DataFrame, day: str
) -> pl.DataFrame:
    """sum_assured and fund_value of the latest valuation on or before `day` (else the first)."""
    columns = [c for c in ("sum_assured", "fund_value") if c in in_force.columns]
    values = (
        in_force.join(contracts.select("contract_id", "contract"), on="contract_id")
        .select("contract", pl.col("valuation_date").cast(pl.Int64).alias("at"), *columns)
        .sort("contract", "at")
    )
    for c in ("sum_assured", "fund_value"):
        if c not in values.columns:
            values = values.with_columns(pl.lit(None, pl.Float64).alias(c))
    keyed = pieces.with_row_index("_piece").sort(day)
    sorted_values = values.sort("at")
    back = keyed.join_asof(
        sorted_values,
        left_on=day,
        right_on="at",
        by="contract",
        strategy="backward",
        check_sortedness=False,
    )
    ahead = keyed.join_asof(
        sorted_values,
        left_on=day,
        right_on="at",
        by="contract",
        strategy="forward",
        check_sortedness=False,
    ).select("_piece", pl.col("sum_assured").alias("_sa"), pl.col("fund_value").alias("_fv"))
    joined = back.join(ahead, on="_piece").sort("_piece")
    return joined.with_columns(
        pl.coalesce("sum_assured", "_sa").fill_null(0.0).alias("sum_assured"),
        pl.coalesce("fund_value", "_fv").fill_null(0.0).alias("fund_value"),
    ).drop("_piece", "_sa", "_fv", "at")


def exposure(
    in_force: pl.DataFrame,
    events: pl.DataFrame | None,
    cut_off: date,
    settings: LifeSettings,
) -> Exposure:
    """Exposure and decrements per cell of the canonical life feeds (CV11)."""
    cut_off = min(cut_off, in_force["valuation_date"].max())  # type: ignore[type-var]
    study = study_period(in_force["valuation_date"].min(), cut_off, settings.reporting_lag_months)  # type: ignore[arg-type]
    contracts = _contracts(in_force, settings.use_sex)
    in_events = events.filter(pl.col("event_date") <= cut_off) if events is not None else None
    known = contracts["contract_id"]
    without = (
        in_events.filter(~pl.col("contract_id").is_in(known.implode())).height
        if in_events is not None
        else 0
    )
    marks = (
        _effective_events(in_events, contracts)
        if in_events is not None
        else pl.DataFrame(
            schema={
                "contract": pl.UInt32,
                "event_date": pl.Date,
                "event_type": pl.String,
                "back": pl.Boolean,
            }
        )
    )
    with_exit = marks.filter(~pl.col("back"))["contract"].unique()
    half = _half_interval_exits(in_force, contracts, with_exit)
    marks = pl.concat([marks, half.cast(marks.schema)])
    spells = _spells(contracts, marks)
    entry = to_days(contracts["entry_date"])
    calendar = settings.study_cells == "calendar_year"
    pieces = _pieces(spells, entry, study, calendar)
    mortality_stop = to_days(pl.Series([study.mortality_end]))[0] + 1
    pieces = pieces.with_columns(
        ((pl.col("hi") - pl.col("lo")) / DAYS_PER_YEAR).alias("central_exposure"),
        (
            (pl.min_horizontal("hi", pl.lit(mortality_stop)) - pl.col("lo")).clip(lower_bound=0)
            / DAYS_PER_YEAR
        ).alias("central_exposure_mortality"),
    )
    pieces = _value_at(pieces, in_force, contracts, "lo").with_columns(
        (pl.col("central_exposure_mortality") * pl.col("sum_assured")).alias(
            "sum_assured_exposure"
        ),
        (pl.col("central_exposure") * pl.col("fund_value")).alias("fund_value_exposure"),
    )
    decrements = _decrements(spells, entry, study, mortality_stop, calendar, in_force, contracts)
    keys = ["contract", "k", "year"]
    exposure_part = pieces.group_by(keys).agg(
        pl.col(
            "central_exposure",
            "central_exposure_mortality",
            "sum_assured_exposure",
            "fund_value_exposure",
        ).sum()
    )
    both = exposure_part.join(decrements, on=keys, how="full", coalesce=True)
    cells = _cells(both, contracts, settings)
    return Exposure(
        cells,
        study,
        settings,
        contracts.height,
        int(marks.filter(~pl.col("back")).height - half.height),
        half.height,
        without,
    )


def _decrements(
    spells: pl.DataFrame,
    entry: np.ndarray,
    study: Study,
    mortality_stop: int,
    calendar: bool,
    in_force: pl.DataFrame,
    contracts: pl.DataFrame,
) -> pl.DataFrame:
    """Decrements in the cell of the day they happen, with the time to the end of the age year
    (initial exposure) and the amounts at the start of the cell."""
    w0 = to_days(pl.Series([study.start]))[0]
    w1 = to_days(pl.Series([study.end]))[0] + 1
    exits = spells.filter(
        pl.col("exit").is_not_null() & (pl.col("stop") >= w0) & (pl.col("stop") < w1)
    )
    who = exits["contract"].to_numpy()
    day = exits["stop"].to_numpy()
    k = whole_years(entry[who], day)
    anniversary = shift_years(entry[who], k)
    to_birthday = (shift_years(entry[who], k + 1) - day) / DAYS_PER_YEAR
    year = year_of(day) if calendar else year_of(anniversary)
    cell_start = np.maximum(jan1(year_of(day)), anniversary) if calendar else anniversary
    frame = pl.DataFrame(
        {
            "contract": who,
            "k": k,
            "year": year,
            "lo": cell_start,
            "exit": exits["exit"],
            "to_birthday": to_birthday,
            "mortality": day < mortality_stop,
        }
    )
    frame = _value_at(frame, in_force, contracts, "lo")
    kind = pl.col("exit")
    death = (kind == DEATH) & pl.col("mortality")
    lapse_like = kind.is_in((*LAPSES, *SURRENDERS))
    return frame.group_by("contract", "k", "year").agg(
        death.sum().alias("deaths"),
        kind.is_in(LAPSES).sum().alias("lapses"),
        kind.is_in(SURRENDERS).sum().alias("surrenders"),
        kind.is_in(OTHER_EXITS).sum().alias("other_exits"),
        pl.col("to_birthday").filter(death).sum().alias("initial_mortality_extra"),
        pl.col("to_birthday").filter(lapse_like).sum().alias("initial_lapse_extra"),
        pl.col("sum_assured").filter(death).sum().alias("sum_assured_deaths"),
        pl.col("fund_value").filter(kind.is_in(SURRENDERS)).sum().alias("fund_value_surrenders"),
    )


def _cells(both: pl.DataFrame, contracts: pl.DataFrame, settings: LifeSettings) -> pl.DataFrame:
    period = "calendar_year" if settings.study_cells == "calendar_year" else "anniversary_year"
    terms = ["segment", "line", "product", *(["sex"] if settings.use_sex else [])]
    joined = both.join(
        contracts.select("contract", *terms, "entry_age", "source_width", "open_band"),
        on="contract",
    ).with_columns(
        (pl.col("entry_age") + pl.col("k")).alias("age"),
        (pl.col("k") + 1).alias("policy_year"),
        pl.col("year").alias(period),
    )
    joined = joined.with_columns(
        band_expr(
            pl.col("age"), settings.age_band_width, pl.col("source_width"), pl.col("open_band")
        ).alias("age_band")
    )
    zero = [
        "central_exposure",
        "central_exposure_mortality",
        "sum_assured_exposure",
        "fund_value_exposure",
        "initial_mortality_extra",
        "initial_lapse_extra",
        "sum_assured_deaths",
        "fund_value_surrenders",
    ]
    counts = ["deaths", "lapses", "surrenders", "other_exits"]
    joined = joined.with_columns(
        pl.col(zero).fill_null(0.0), pl.col(counts).fill_null(0).cast(pl.Int64)
    )
    keys = [*terms, period, "age", "age_band", "policy_year"]
    cells = joined.group_by(keys).agg(pl.col(*zero, *counts).sum())
    return cells.select(
        *keys,
        "central_exposure",
        "central_exposure_mortality",
        (pl.col("central_exposure_mortality") + pl.col("initial_mortality_extra")).alias(
            "initial_exposure_mortality"
        ),
        (pl.col("central_exposure") + pl.col("initial_lapse_extra")).alias(
            "initial_exposure_lapse"
        ),
        *counts,
        "sum_assured_exposure",
        "fund_value_exposure",
        "sum_assured_deaths",
        "fund_value_surrenders",
    ).sort(keys, nulls_last=True)
