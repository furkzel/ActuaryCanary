"""Orchestration: simulate a scenario, then write spreadsheets, canonical parquet and truth."""

from dataclasses import dataclass
from pathlib import Path

import polars as pl
import yaml

from actuarycanary import __version__
from actuarycanary.synthetic import feeds, truth
from actuarycanary.synthetic.claims import ClaimWorld, build_claims
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
from actuarycanary.synthetic.portfolio import Policies, PremiumRows, build_policies, build_premiums
from actuarycanary.synthetic.reinsurance import Reinsurance
from actuarycanary.synthetic.scenario import Scenario, SizeSpec, load_scenario, sized
from actuarycanary.synthetic.writer import (
    fits_in_worksheet,
    sha256,
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
    premiums = build_premiums(scenario, policies, streams)
    world = build_claims(scenario, spec, market, policies, streams)
    reinsurance = Reinsurance(scenario, world)

    valuations, _, _ = feeds.valuation_rows(world, reinsurance, scenario, spec)
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

    claims = truth._claim_frame(scenario, world, reinsurance, market, cut_off)
    exposure = truth.exposure_by_year(scenario, spec, policies)
    tables = {
        "ultimates": truth.ultimates(scenario, spec, claims, policies, premiums),
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
                "detail": f"cost {shock.cost_base:g} at base-date prices",
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


def write_outputs(sim: Simulation, out: Path) -> dict[str, object]:
    """Write spreadsheets, canonical parquet and truth under `out`; return the manifest."""
    scenario = sim.scenario
    (out / "canonical").mkdir(parents=True, exist_ok=True)
    (out / "truth").mkdir(parents=True, exist_ok=True)
    streams = Streams(scenario.meta.seed)
    dictionaries = Dictionaries()
    log = MessLog()
    plans: dict[str, list[SheetPlan]] = {}
    skipped: dict[str, str] = {}
    for feed, sheets in sim.frames.items():
        plans[feed] = []
        for key, frame in sheets.items():
            name = sheet_name_for(feed, key, scenario, streams)
            plans[feed].append(
                layout_sheet(scenario, dictionaries, streams, feed, key, frame, log, name)
            )
        if all(fits_in_worksheet(s) for s in plans[feed]):
            write_workbook(out / f"{feed}.xlsx", plans[feed])
        else:
            rows = max(s.n_rows for s in plans[feed])
            skipped[f"{feed}.xlsx"] = f"{rows} data rows exceed the worksheet limit; parquet only"
        write_parquet(out / "canonical" / f"{feed}.parquet", pl.concat(sheets.values()))

    layout = pl.DataFrame(
        [
            {
                "file": f"{feed}.xlsx",
                "sheet": s.name,
                "title_rows": len(s.title_rows),
                "header_row": s.header_row,
                "first_data_row": s.header_row + 1,
                "data_rows": s.n_rows,
                "written": f"{feed}.xlsx" not in skipped,
            }
            for feed, sheets in plans.items()
            for s in sheets
        ]
    )
    first_data = {
        (f"{feed}"): s.header_row + 1 for feed, sheets in plans.items() for s in sheets[:1]
    }
    fault_table = pl.DataFrame(
        [
            {
                "fault_type": f.fault_type,
                "file": f"{f.file}.xlsx",
                "key": f.key,
                "row": f.row,
                "sheet_row": first_data[f.file] + f.row,
                "detail": f.detail,
            }
            for f in sim.faults
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
    write_csv(truth_dir / "injected_faults.csv", fault_table)
    write_csv(truth_dir / "anomalies.csv", anomalies(sim, fault_table))
    write_csv(truth_dir / "column_map.csv", pl.DataFrame(log.columns))
    write_csv(
        truth_dir / "value_map.csv",
        pl.DataFrame(
            log.values,
            schema={"file": pl.String, "field": pl.String, "label": pl.String, "class": pl.String},
        ),
    )
    write_csv(
        truth_dir / "date_formats.csv",
        pl.DataFrame(
            log.dates,
            schema={
                "file": pl.String,
                "field": pl.String,
                "text_format": pl.String,
                "text_share": pl.String,
            },
        ),
    )
    write_csv(truth_dir / "layout.csv", layout)
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
    (truth_dir / "scenario.yaml").write_text(
        yaml.safe_dump(
            {
                "size": sim.size_name,
                "size_spec": sim.size.model_dump(mode="json"),
                "scenario": scenario.model_dump(mode="json", by_alias=True),
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
        "spreadsheets_skipped": skipped,
        "sha256": {p.relative_to(out).as_posix(): sha256(p) for p in files},
    }
    (out / "manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8", newline="\n"
    )
    return manifest


def synthesize(scenario: str, size: str, out: Path) -> dict[str, object]:
    """Simulate and write one scenario at one size."""
    return write_outputs(simulate(scenario, size), out)
