"""The table of the seed stability script (A1b, R04, record 0779) on a small frame with a known
spread; the 20-seed run itself is a documented command, not a test."""

import polars as pl
import pytest

from docs.tools.seed_stability import (
    TARGET,
    parse_seeds,
    simulations_register,
    spread_table,
    verdict,
)


def _runs() -> pl.DataFrame:
    # all lines: VaR 100, 101, 99 (mean 100, range 2 -> spread 2 %); TVaR 200, 200, 200
    rows = []
    for seed, var in ((1, 100.0), (2, 101.0), (3, 99.0)):
        rows.append(
            {"seed": seed, "segment": "All lines", "line": "All lines", "simulations": 10,
             "mean": 50.0, "var_99_5": var, "tvar_99": 200.0}
        )  # fmt: skip
        rows.append(
            {"seed": seed, "segment": "S", "line": "L", "simulations": 10,
             "mean": 10.0, "var_99_5": 10.0 * seed, "tvar_99": 20.0}
        )  # fmt: skip
    return pl.DataFrame(rows)


def test_the_spread_is_largest_minus_smallest_over_the_mean_of_the_seeds() -> None:
    table = spread_table(_runs())
    row = table.filter(
        (pl.col("segment") == "All lines") & (pl.col("statistic") == "var_99_5")
    ).to_dicts()[0]
    assert (row["seeds"], row["minimum"], row["maximum"]) == (3, 99.0, 101.0)
    assert row["mean_over_seeds"] == pytest.approx(100.0)
    assert row["spread"] == pytest.approx(0.02)
    assert row["max_deviation"] == pytest.approx(0.01)
    flat = table.filter((pl.col("segment") == "All lines") & (pl.col("statistic") == "tvar_99"))
    assert flat["spread"].to_list() == [0.0]
    line = table.filter((pl.col("line") == "L") & (pl.col("statistic") == "var_99_5"))
    assert line["spread"].to_list() == [pytest.approx((30.0 - 10.0) / 20.0)]


def test_the_verdict_reads_the_all_lines_rows_against_the_target() -> None:
    assert verdict(spread_table(_runs())) == {"var_99_5": True, "tvar_99": True}
    assert verdict(spread_table(_runs()), target=0.01) == {"var_99_5": False, "tvar_99": True}
    assert TARGET == 0.02


def test_seeds_are_read_from_ranges_and_lists() -> None:
    assert parse_seeds("1-4,9") == [1, 2, 3, 4, 9]
    assert parse_seeds("7") == [7]
    with pytest.raises(ValueError):
        parse_seeds("1-3,2")


def test_the_size_of_the_study_is_a_register_entry_for_every_scope() -> None:
    assert simulations_register(None).entries == ()
    (entry,) = simulations_register(20_000).entries
    assert (entry.method, entry.name, entry.value) == ("MT11", "n_simulations", 20_000)
