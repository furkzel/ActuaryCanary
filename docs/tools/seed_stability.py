"""How far the simulated range moves with the seed (A1b, R04, record 0779).

Runs the pipeline on a folder (default: the demo, with its curve) once for each seed, with the
seed of the bootstrap (MT11, one stream per line, `methods.seeding`) and of the all-lines total
(M12) set to that seed, and writes for every seed the nominal mean, the VaR 99.5 % and the
TVaR 99 % of the simulation of each line and of all lines, and then, per line, the smallest and
the largest value over the seeds and their spread (largest minus smallest over the mean of the
seeds). The aggregation is the run's own (`run_uncertainty`, M12); nothing is added up here.

    uv run python -m docs.tools.seed_stability <output folder> [--folder F] [--seeds 1-20]
        [--simulations N] [--budget-minutes 20]

It writes only into the output folder (a run's own folder is removed after its figures are
read), stops with a message when the next seed would not fit in the time budget, and prints
what it did. It is not part of a user's run: twenty bootstraps are twenty runs.
"""

import argparse
import shutil
import sys
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from functools import partial
from pathlib import Path

import polars as pl

import actuarycanary.pipeline as pipeline
from actuarycanary.cli.demo import DEMO_CURVE, find_demo_folder
from actuarycanary.convert.discount import DiscountSettings
from actuarycanary.methods.assumptions import ANY_SCOPE, Assumption, AssumptionsRegister
from actuarycanary.modules.uncertainty import BOOTSTRAP_SOURCE, UncertaintyResult

TARGET = 0.02  # the spread asked of VaR 99.5 % and TVaR 99 % across the seeds
STATISTICS = ("mean", "var_99_5", "tvar_99")
SOURCE_COLUMNS = {"mean": "mean", "var_99_5": "value_at_risk", "tvar_99": "tail_value_at_risk"}
RUNS_NAME = "seed_stability_runs.csv"
SUMMARY_NAME = "seed_stability_summary.csv"
ALL_LINES = "All lines"


def parse_seeds(text: str) -> list[int]:
    """'1-20' or '3,5,8' or '1-4,9'."""
    seeds: list[int] = []
    for part in text.split(","):
        low, _, high = part.partition("-")
        seeds += range(int(low), int(high or low) + 1)
    if not seeds or len(set(seeds)) != len(seeds):
        raise ValueError(f"the seeds {text!r} are empty or repeat")
    return seeds


def figures(uncertainty: UncertaintyResult, seed: int, simulations: int) -> list[dict]:
    """The nominal bootstrap total of every line and of all lines, as rows for this seed."""
    risk = uncertainty.risk.filter(
        (pl.col("source") == BOOTSTRAP_SOURCE)
        & (pl.col("value_basis") == "NOMINAL")
        & (pl.col("origin_period") == "Total")
    )
    return [
        {
            "seed": seed,
            "segment": r["segment"],
            "line": r["line"],
            "simulations": simulations,
            **{name: r[column] for name, column in SOURCE_COLUMNS.items()},
        }
        for r in risk.to_dicts()
    ]


def spread_table(runs: pl.DataFrame) -> pl.DataFrame:
    """Per line and statistic over the seeds: seeds, mean, smallest, largest, the spread (largest
    minus smallest over the mean) and the largest deviation from the mean over the mean."""
    rows = []
    for (segment, line), group in runs.group_by(["segment", "line"], maintain_order=True):
        for name in STATISTICS:
            values = group[name].drop_nulls()
            if not values.len():
                continue
            centre = float(values.mean())  # type: ignore[arg-type]
            low, high = float(values.min()), float(values.max())  # type: ignore[arg-type]
            rows.append(
                {
                    "segment": segment,
                    "line": line,
                    "statistic": name,
                    "seeds": values.len(),
                    "mean_over_seeds": centre,
                    "minimum": low,
                    "maximum": high,
                    "spread": (high - low) / centre if centre else float("nan"),
                    "max_deviation": max(high - centre, centre - low) / centre
                    if centre
                    else float("nan"),
                }
            )
    return pl.DataFrame(rows)


def verdict(table: pl.DataFrame, target: float = TARGET) -> dict[str, bool]:
    """Whether the spread of VaR 99.5 % and of TVaR 99 % of all lines is within the target."""
    total = table.filter(pl.col("segment") == ALL_LINES)
    return {
        row["statistic"]: bool(row["spread"] <= target)
        for row in total.to_dicts()
        if row["statistic"] in ("var_99_5", "tvar_99")
    }


@contextmanager
def seeded(seed: int) -> Iterator[None]:
    """The pipeline with `seed` as the seed of the bootstrap and of the all-lines total."""
    tier_b, uncertainty = pipeline.TierBInputs, pipeline.run_uncertainty
    pipeline.TierBInputs = partial(tier_b, seed=seed)  # type: ignore[assignment,misc]
    pipeline.run_uncertainty = partial(uncertainty, seed=seed)  # type: ignore[assignment]
    try:
        yield
    finally:
        pipeline.TierBInputs, pipeline.run_uncertainty = tier_b, uncertainty


def simulations_register(simulations: int | None) -> AssumptionsRegister:
    if simulations is None:
        return AssumptionsRegister()
    entry = Assumption(
        method="MT11", name="n_simulations", scope=ANY_SCOPE, target="", value=simulations,
        who="seed stability script", why="size of the stability study (record 0779)",
    )  # fmt: skip
    return AssumptionsRegister(entries=(entry,))


def render(table: pl.DataFrame) -> str:
    lines = [
        f"{'segment':<10}{'line':<17}{'statistic':<10}{'seeds':>6}{'mean':>16}"
        f"{'minimum':>16}{'maximum':>16}{'spread':>9}{'max dev':>9}"
    ]
    for r in table.to_dicts():
        lines.append(
            f"{r['segment']:<10}{r['line']:<17}{r['statistic']:<10}{r['seeds']:>6}"
            f"{r['mean_over_seeds']:>16,.0f}{r['minimum']:>16,.0f}{r['maximum']:>16,.0f}"
            f"{r['spread']:>9.2%}{r['max_deviation']:>9.2%}"
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("output", type=Path, help="folder for the tables (outside the repository)")
    parser.add_argument("--folder", type=Path, default=None, help="input folder (default: demo)")
    parser.add_argument("--seeds", default="1-20")
    parser.add_argument("--simulations", type=int, default=None, help="default: that of MT11")
    parser.add_argument("--budget-minutes", type=float, default=20.0)
    args = parser.parse_args(argv)

    output: Path = args.output.resolve()
    if Path.cwd().resolve() in (output, *output.parents) and (output / "pyproject.toml").exists():
        print("The output folder is the repository: give a folder outside it.", file=sys.stderr)
        return 2
    output.mkdir(parents=True, exist_ok=True)
    seeds = parse_seeds(args.seeds)
    folder = args.folder or find_demo_folder()
    settings = pipeline.RunSettings(
        discount=DiscountSettings(curve_id=DEMO_CURVE)
        if args.folder is None
        else DiscountSettings(),
        assumptions=simulations_register(args.simulations),
    )
    size = args.simulations or "MT11 default"
    print(f"Input {folder}; seeds {seeds[0]}..{seeds[-1]} ({len(seeds)}); simulations {size}")
    print(f"Time budget {args.budget_minutes:g} min")
    started = time.monotonic()
    rows: list[dict] = []
    longest = 0.0
    done: list[int] = []
    for seed in seeds:
        elapsed = time.monotonic() - started
        if elapsed + longest > args.budget_minutes * 60:
            print(
                f"Stopped before seed {seed}: {elapsed / 60:.1f} min used, the next seed needs "
                f"about {longest / 60:.1f} min and the budget is {args.budget_minutes:g} min."
            )
            break
        begin = time.monotonic()
        with seeded(seed):
            result = pipeline.run(
                folder, output / "runs", settings, cache_dir=output / ".cache", profiles_dir=None
            )
        if not isinstance(result.uncertainty, UncertaintyResult):
            print(f"Seed {seed}: no uncertainty result: {result.uncertainty}", file=sys.stderr)
            return 1
        used = {
            g.tier_b.bootstrap.seed
            for g in result.reserving.groups
            if g.tier_b is not None and hasattr(g.tier_b.bootstrap, "seed")
        }
        if used != {seed}:
            print(f"Seed {seed}: the bootstrap used the seeds {used}; stopped.", file=sys.stderr)
            return 1
        n = next(
            g.tier_b.bootstrap.n_simulations
            for g in result.reserving.groups
            if g.tier_b is not None and hasattr(g.tier_b.bootstrap, "n_simulations")
        )
        rows += figures(result.uncertainty, seed, n)
        shutil.rmtree(result.folder, ignore_errors=True)
        done.append(seed)
        longest = max(longest, time.monotonic() - begin)
        print(f"  seed {seed:>3} done in {time.monotonic() - begin:5.1f} s")
    shutil.rmtree(output / "runs", ignore_errors=True)
    if not rows:
        print("No seed finished; nothing written.")
        return 1
    runs = pl.DataFrame(rows)
    runs.write_csv(output / RUNS_NAME)
    table = spread_table(runs)
    table.write_csv(output / SUMMARY_NAME)
    print(
        f"\nSeeds done: {len(done)} of {len(seeds)} in {(time.monotonic() - started) / 60:.1f} min"
    )
    print(render(table))
    found = verdict(table)
    words = ", ".join(f"{k} {'within' if ok else 'ABOVE'}" for k, ok in found.items())
    print(f"\nAll lines, spread against the target of {TARGET:.0%}: {words}")
    print(f"Wrote {output / RUNS_NAME} and {output / SUMMARY_NAME}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
