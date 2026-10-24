"""Orchestration: simulate a scenario, then write spreadsheets, canonical parquet and truth."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl
import yaml

from actuarycanary import __version__
from actuarycanary.synthetic import feeds, truth
from actuarycanary.synthetic.claims import SHOCK, ClaimWorld, build_claims
from actuarycanary.synthetic.days import to_day
from actuarycanary.synthetic.draws import Streams
from actuarycanary.synthetic.faults import Fault, inject_faults
from actuarycanary.synthetic.market import Market, build_market
from actuarycanary.synthetic.messy import (
    Dictionaries,
    MessLog,
    SheetPlan,
    layout_sheet,
    sheet_name_for,
)
from actuarycanary.synthetic.phase2 import PHASE2_FEEDS, TRUTH_USERS, Phase2Output, build_phase2
from actuarycanary.synthetic.portfolio import Policies, PremiumRows, build_policies, build_premiums
from actuarycanary.synthetic.reinsurance import Reinsurance
from actuarycanary.synthetic.scenario import Scenario, SizeSpec, load_scenario, sized
from actuarycanary.synthetic.writer import (
    sha256,
    split_workbooks,
    write_csv,
    write_parquet,
    write_workbook,
)


@dataclass
class Simulation:
    scenario: Scenario
    size_name: str
    size: SizeSpec
    market: Market
    policies: Policies
    premiums: PremiumRows
    world: ClaimWorld
    reinsurance: Reinsurance
    frames: dict[str, dict[str, pl.DataFrame]]  # feed -> sheet key -> table, faults included
    clean: dict[str, pl.DataFrame]  # claim_valuations and claims before faults
    faults: list[Fault]
    truth: dict[str, pl.DataFrame]
    phase2: Phase2Output


def simulate(scenario: str | Scenario, size: str | SizeSpec) -> Simulation:
    """Run the whole simulation in memory. Nothing is written."""
    if isinstance(scenario, str):
        scenario = load_scenario(scenario)
    size_name = size if isinstance(size, str) else "custom"
    spec = sized(scenario, size)
    streams = Streams(scenario.meta.seed)
    cut_off = to_day(scenario.meta.valuation.last)

    market = build_market(scenario, streams)
    policies = build_policies(scenario, spec, market, streams)
    premiums = build_premiums(scenario, policies, streams, market)
    world = build_claims(scenario, spec, market, policies, streams)
    reinsurance = Reinsurance(scenario, world)

    valuations, valuation_claim, valuation_day = feeds.valuation_rows(
        world, reinsurance, scenario, spec
    )
    clean = {
        "claim_valuations": valuations,
        "claims": feeds.claims_table(world, scenario),
        "policies": feeds.policies_table(policies, scenario),
        "premiums": feeds.premiums_table(policies, premiums),
        "expenses": feeds.expenses_table(
            scenario, spec, market, world, policies, premiums, streams
        ),
    }
    faulted, faults = inject_faults(scenario, spec, clean, world, streams)

    frames: dict[str, dict[str, pl.DataFrame]] = {feed: {feed: faulted[feed]} for feed in faulted}
    frames["market"] = feeds.market_sheets(scenario, market)
    later = build_phase2(
        scenario,
        spec,
        size_name,
        market,
        policies,
        premiums,
        world,
        reinsurance,
        valuations,
        valuation_claim,
        valuation_day,
        clean["expenses"],
        streams,
    )
    frames.update(later.frames)

    claims = truth._claim_frame(scenario, world, reinsurance, market, cut_off)
    exposure = truth.exposure_by_year(scenario, spec, policies)
    tables = {
        "ultimates": truth.ultimates(scenario, spec, claims, policies, premiums, market, cut_off),
        "ibnr_by_valuation": truth.ibnr_by_valuation(scenario, spec, world, cut_off),
        "development_pattern": truth.development_pattern(scenario, spec, world, cut_off),
        "frequency_severity": truth.frequency_severity(scenario, spec, world, exposure),
        "inflation": truth.inflation_path(scenario, market, cut_off),
    }
    return Simulation(
        scenario,
        size_name,
        spec,
        market,
        policies,
        premiums,
        world,
        reinsurance,
        frames,
        clean,
        faults,
        tables,
        later,
    )


def anomalies(sim: Simulation, fault_rows: pl.DataFrame) -> pl.DataFrame:
    """Everything the data deliberately contains that an early-warning view should find."""
    scenario, world = sim.scenario, sim.world
    rows: list[dict[str, str]] = []
    for fault in fault_rows.iter_rows(named=True):
        rows.append(
            {
                "origin": "data_fault",
                "type": fault["fault_type"],
                "line": "",
                "date": "",
                "reference": f"{fault['file']}:{fault['key']}",
                "detail": fault["detail"],
            }
        )
    for index, code in enumerate(world.event_codes):
        members = int((world.c_event == index).sum())
        day = world.event_dates[index]
        rows.append(
            {
                "origin": "world",
                "type": "catastrophe_event",
                "line": "",
                "date": pl.Series([day]).cast(pl.Int32).cast(pl.Date).dt.to_string("%Y-%m-%d")[0],
                "reference": code,
                "detail": f"{members} claims",
            }
        )
    for change in scenario.reserving_practice_changes:
        rows.append(
            {
                "origin": "world",
                "type": "reserving_practice_change",
                "line": change.line,
                "date": change.from_.isoformat(),
                "reference": "",
                "detail": f"case reserve bias becomes {change.initial_bias:+g}",
            }
        )
    for shock in scenario.large_claims:
        rows.append(
            {
                "origin": "world",
                "type": "large_loss_shock",
                "line": shock.line,
                "date": shock.date.isoformat(),
                "reference": shock.label,
                "detail": f"cost {shock.cost_base:g} TRY at base-date prices",
            }
        )
    for name, line in scenario.lines.items():
        if line.large_events is None:
            continue
        mine = np.flatnonzero(
            (world.c_kind == SHOCK)
            & (world.c_line == name)
            & (world.c_label == line.large_events.label)
        )
        for claim in mine[np.argsort(world.c_occ[mine], kind="stable")]:
            cost = float(world.c_cost[claim] * world.c_fx_start[claim])
            rows.append(
                {
                    "origin": "world",
                    "type": "large_loss_event",
                    "line": name,
                    "date": pl.Series([int(world.c_occ[claim])])
                    .cast(pl.Int32)
                    .cast(pl.Date)
                    .dt.to_string("%Y-%m-%d")[0],
                    "reference": line.large_events.label,
                    "detail": f"cost {cost:g} TRY at base-date prices",
                }
            )
    for year, rate in sorted(scenario.market.cpi.annual_rate_by_year.items()):
        if rate >= 0.5:
            rows.append(
                {
                    "origin": "world",
                    "type": "high_inflation_year",
                    "line": "",
                    "date": f"{year}-12-31",
                    "reference": scenario.market.cpi.series_id,
                    "detail": f"annual rate {rate:.0%}",
                }
            )
    return pl.DataFrame(
        rows,
        schema={
            "origin": pl.String,
            "type": pl.String,
            "line": pl.String,
            "date": pl.String,
            "reference": pl.String,
            "detail": pl.String,
        },
    )


def _of(rows: list[dict[str, str]], later: bool) -> list[dict[str, str]]:
    """The log rows of the feeds added later (`later`) or of the first six."""
    return [r for r in rows if (r["file"] in PHASE2_FEEDS) == later]


LAYOUT_SCHEMA = {
    "file": pl.String,
    "sheet": pl.String,
    "title_rows": pl.Int64,
    "header_row": pl.Int64,
    "first_data_row": pl.Int64,
    "data_rows": pl.Int64,
    "written": pl.Boolean,
}


def locate(workbooks: list[tuple[str, list[SheetPlan]]], row: int) -> tuple[str, int]:
    """The workbook holding 0-based data row `row` of a feed's first sheet, and the worksheet
    row it sits on there."""
    for file, parts in workbooks:
        first = parts[0]
        if row < first.n_rows:
            return file, first.header_row + 1 + row
        row -= first.n_rows
    raise IndexError("row is past the last workbook")


def write_outputs(sim: Simulation, out: Path) -> dict[str, object]:
    """Write spreadsheets, canonical parquet and truth under `out`; return the manifest."""
    scenario = sim.scenario
    (out / "canonical").mkdir(parents=True, exist_ok=True)
    (out / "truth").mkdir(parents=True, exist_ok=True)
    streams = Streams(scenario.meta.seed)
    dictionaries = Dictionaries()
    log = MessLog()
    plans: dict[str, list[SheetPlan]] = {}
    workbooks: dict[str, list[tuple[str, list[SheetPlan]]]] = {}
    for feed, sheets in sim.frames.items():
        plans[feed] = []
        for key, frame in sheets.items():
            name = sheet_name_for(feed, key, scenario, streams)
            plans[feed].append(
                layout_sheet(scenario, dictionaries, streams, feed, key, frame, log, name)
            )
        workbooks[feed] = split_workbooks(feed, plans[feed])
        for file, parts in workbooks[feed]:
            write_workbook(out / file, parts)
        write_parquet(out / "canonical" / f"{feed}.parquet", pl.concat(sheets.values()))

    layout = pl.DataFrame(
        [
            {
                "file": file,
                "sheet": s.name,
                "title_rows": len(s.title_rows),
                "header_row": s.header_row,
                "first_data_row": s.header_row + 1,
                "data_rows": s.n_rows,
                "written": True,
            }
            for feed in plans
            for file, parts in workbooks[feed]
            for s in parts
        ],
        schema=LAYOUT_SCHEMA,
    )
    # the logs of the feeds added later go to files of their own, so that the files of the
    # first six feeds stay byte for byte what they were
    layout_later = layout.filter(
        pl.col("file").str.replace(r"(_part\d+)?\.xlsx$", "").is_in(PHASE2_FEEDS)
    )
    layout = layout.join(layout_later, on=layout.columns, how="anti")
    fault_table = pl.DataFrame(
        [
            {
                "fault_type": f.fault_type,
                "file": file,
                "key": f.key,
                "row": f.row,
                "sheet_row": sheet_row,
                "detail": f.detail,
            }
            for f in sim.faults
            for file, sheet_row in [locate(workbooks[f.file], f.row)]
        ],
        schema={
            "fault_type": pl.String,
            "file": pl.String,
            "key": pl.String,
            "row": pl.Int64,
            "sheet_row": pl.Int64,
            "detail": pl.String,
        },
    )
    personal = [c for c in log.columns if c["kind"].startswith("personal")]
    truth_dir = out / "truth"
    for name, table in sim.truth.items():
        write_csv(truth_dir / f"{name}.csv", table)
    write_csv(truth_dir / "money_columns.csv", truth.money_columns_table())
    write_csv(truth_dir / "injected_faults.csv", fault_table)
    write_csv(truth_dir / "anomalies.csv", anomalies(sim, fault_table))
    for suffix, later in (("", False), ("_phase2", True)):
        if later and not any(feed in sim.phase2.frames for feed in PHASE2_FEEDS):
            continue
        write_csv(truth_dir / f"column_map{suffix}.csv", pl.DataFrame(_of(log.columns, later)))
        write_csv(
            truth_dir / f"value_map{suffix}.csv",
            pl.DataFrame(
                _of(log.values, later),
                schema={
                    "file": pl.String,
                    "field": pl.String,
                    "label": pl.String,
                    "class": pl.String,
                },
            ),
        )
        write_csv(
            truth_dir / f"date_formats{suffix}.csv",
            pl.DataFrame(
                _of(log.dates, later),
                schema={
                    "file": pl.String,
                    "field": pl.String,
                    "text_format": pl.String,
                    "text_share": pl.String,
                },
            ),
        )
        write_csv(truth_dir / f"layout{suffix}.csv", layout_later if later else layout)
    write_csv(
        truth_dir / "personal_data_columns.csv",
        pl.DataFrame(
            personal,
            schema={
                "file": pl.String,
                "sheet": pl.String,
                "header": pl.String,
                "field": pl.String,
                "kind": pl.String,
            },
        ),
    )
    for name, table in sim.phase2.truth.items():
        write_csv(truth_dir / f"{name}.csv", table)
    if sim.phase2.truth:
        write_csv(
            truth_dir / "money_columns_phase2.csv", truth.money_columns_table(sim.phase2.money)
        )
    for relative, table in sim.phase2.files.items():
        target = out / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        write_csv(target, table)
    (truth_dir / "phase2_scenario.yaml").write_text(
        yaml.safe_dump(
            {"phase2": scenario.phase2.model_dump(mode="json"), "truth_users": TRUTH_USERS},
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
        newline="\n",
    )
    (truth_dir / "scenario.yaml").write_text(
        yaml.safe_dump(
            {
                "size": sim.size_name,
                "size_spec": sim.size.model_dump(mode="json"),
                "scenario": scenario.model_dump(
                    mode="json",
                    by_alias=True,
                    # an unused option is left out, so older scenarios keep their exact dump
                    exclude={
                        "lines": {
                            name: {"large_events"}
                            for name, line in scenario.lines.items()
                            if line.large_events is None
                        },
                        "phase2": True,
                    },
                ),
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
        newline="\n",
    )

    files = sorted(p for p in out.rglob("*") if p.is_file() and p.name != "manifest.yaml")
    manifest: dict[str, object] = {
        "scenario": scenario.name,
        "size": sim.size_name,
        "seed": scenario.meta.seed,
        "generator_version": __version__,
        "rows": {
            feed: sum(f.height for f in sheets.values()) for feed, sheets in sim.frames.items()
        },
        "claims_simulated": len(sim.world),
        "spreadsheets_skipped": {},
        "sha256": {p.relative_to(out).as_posix(): sha256(p) for p in files},
    }
    (out / "manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8", newline="\n"
    )
    return manifest


def synthesize(scenario: str, size: str, out: Path) -> dict[str, object]:
    """Simulate and write one scenario at one size."""
    return write_outputs(simulate(scenario, size), out)
