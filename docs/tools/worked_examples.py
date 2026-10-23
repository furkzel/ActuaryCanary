"""Worked examples of the method notes, computed by the platform's own code (`just notes`).

Every number in the worked example of a note in docs/methods/ comes from here: the 4 x 4 hand
fixtures of tests/fixtures/hand/ (MT02 to MT05, MT10, the ratios and the inflation example), the
three-claim fixture of the MT01 test, the GenIns benchmark triangle (MT06, which needs more than
four origins) and the fixtures of the MT08 and MT09 tests. A note holds its example between the
markers below; this script rewrites what lies between them, and
`python -m docs.tools.worked_examples` without options (the docs test) fails when a note
differs from what the code gives today.
"""

import math
import re
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

from actuarycanary.io.excel import SOURCE_ROW
from actuarycanary.methods.bornhuetter_ferguson import BornhuetterFerguson, bornhuetter_ferguson
from actuarycanary.methods.cape_cod import CapeCod, cape_cod
from actuarycanary.methods.chain_ladder import Average, ChainLadder, chain_ladder
from actuarycanary.methods.expected_loss_ratio import ExpectedLossRatio, expected_loss_ratio
from actuarycanary.methods.inflation_adjusted import (
    InflationAdjusted,
    inflation_adjusted_chain_ladder,
)
from actuarycanary.methods.isolation_forest import FEATURES, isolation_forest_flags
from actuarycanary.methods.mack import Mack, mack
from actuarycanary.methods.robust_z import robust_z_flags
from actuarycanary.methods.selection import Choice, Selection, select_ultimates
from actuarycanary.structures.triangles import TriangleSettings, build_triangles
from tests.benchmarks.load import Triangle, load_benchmark, load_hand
from tests.structures.test_mt01_triangles import GROUP, OCCURRENCE, ROWS

ROOT = Path(__file__).resolve().parents[2]
NOTES = ROOT / "docs" / "methods"
BEGIN = "<!-- worked-example:begin (written by docs/tools/worked_examples.py; do not edit) -->"
END = "<!-- worked-example:end -->"
BLOCK = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.DOTALL)

HAND = load_hand()
ORIGINS = [str(o) for o in HAND["expected"]["origins"]]
AGES = HAND["expected"]["ages"]
PREMIUM = np.array(HAND["expected"]["earned_premium"], dtype=float)
PRIOR = 0.6  # the prior loss ratio of the hand fixture (tests/fixtures/hand/expected.yaml)
CUT_OFF = date(2024, 12, 31)
TREES = 50


def number(value: float, places: int = 4) -> str:
    """Up to `places` decimals, trailing zeros dropped, thousands separated."""
    if value is None or not math.isfinite(value):
        return "-"
    text = f"{value:,.{places}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


def table(header: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    def cell(value: object) -> str:
        return number(float(value)) if isinstance(value, float | np.floating) else str(value)

    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in rows]
    return "\n".join(lines)


def triangle_table(values: np.ndarray, origins: Sequence[str], ages: Sequence[int]) -> str:
    rows = [
        [origin, *["" if np.isnan(v) else number(float(v), 2) for v in row]]
        for origin, row in zip(origins, values, strict=True)
    ]
    return table(["Origin", *[f"{a} months" for a in ages]], rows)


def hand_triangle(measure: str) -> np.ndarray:
    triangle: Triangle = HAND[measure]
    return np.array([[np.nan if v is None else v for v in row] for row in triangle["values"]])


def fitted(cumulative: np.ndarray) -> ChainLadder:
    result = chain_ladder(cumulative)
    assert isinstance(result, ChainLadder)
    return result


def per_origin(header: Sequence[str], columns: Sequence[np.ndarray]) -> str:
    rows = [[ORIGINS[i], *[column[i] for column in columns]] for i in range(len(ORIGINS))]
    return table(["Origin", *header], rows)


def as_of(claim: str, day: date) -> tuple[float, float]:
    """Paid and case reserve of a claim as known at `day`: its last row on or before it."""
    known = [r for r in ROWS if r[0] == claim and r[1] <= day]
    return (known[-1][2], known[-1][3]) if known else (0.0, 0.0)


def as_of_note(paid) -> str:
    """How the cell of origin 2023 at 18 months is built from the rows (as-of rule)."""
    day = paid.valuation_points[paid.calendar[0, 1]]
    a, b = as_of("A", day)[0], as_of("B", day)[0]
    return (
        f"How one cell is built: origin 2023 at {paid.ages[1]} months is the position at "
        f"{day.isoformat()}. Claim A has no row on that day, so its last row (December 2023, "
        f"closed) is carried forward: paid {number(a, 0)}; claim B has paid {number(b, 0)}; the "
        f"cell is {number(a, 0)} + {number(b, 0)} = {number(a + b, 0)}. Claim C belongs to "
        "origin 2024."
    )


def mt01() -> str:
    claims = pl.DataFrame(
        {
            "claim_id": list(OCCURRENCE),
            "occurrence_date": list(OCCURRENCE.values()),
            "segment": [GROUP[0]] * 3,
            "line": [GROUP[1]] * 3,
            SOURCE_ROW: [2, 3, 4],
        },
        schema_overrides={"occurrence_date": pl.Date},
    )
    valuations = pl.DataFrame(
        {
            "claim_id": [r[0] for r in ROWS],
            "valuation_date": [r[1] for r in ROWS],
            "paid_to_date": [r[2] for r in ROWS],
            "case_reserve": [r[3] for r in ROWS],
            "status": [r[4] for r in ROWS],
            "currency": ["TRY"] * len(ROWS),
            SOURCE_ROW: list(range(2, len(ROWS) + 2)),
        },
        schema_overrides={"paid_to_date": pl.Float64, "case_reserve": pl.Float64},
    )
    built = build_triangles(valuations, claims, TriangleSettings(), {"TRY": 1.0}, "TRY")
    paid, incurred = built.get("paid", GROUP), built.get("incurred", GROUP)
    claim_rows = [[r[0], r[1].isoformat(), number(r[2], 2), number(r[3], 2), r[4]] for r in ROWS]
    return "\n\n".join(
        [
            "Three claims of one line (the fixture of the MT01 test, worked by hand there). "
            "Claim A has no row for April 2023, closes in December 2023, reopens in August 2024 "
            "and closes again; B is reported in January 2024; C occurs in 2024. Cut-off "
            f"{built.cut_off.isoformat()}.",
            table(
                ["Claim", "Valuation date", "Paid to date", "Case reserve", "Status"], claim_rows
            ),
            "Cumulative paid, annual origins and annual development counted back from the "
            "cut-off (ages 6, 18 and 30 months, because the cut-off falls mid-year):",
            triangle_table(paid.cumulative, paid.origins, paid.ages),
            "Incremental paid (each cell minus the one to its left):",
            triangle_table(paid.incremental, paid.origins, paid.ages),
            "Cumulative incurred (paid plus case reserve, as known at each valuation point):",
            triangle_table(incurred.cumulative, incurred.origins, incurred.ages),
            as_of_note(paid),
        ]
    )


def mt02() -> str:
    chain = fitted(hand_triangle("paid"))
    ratios = [
        [ORIGINS[i], *["" if np.isnan(v) else number(float(v)) for v in chain.link_ratios[i]]]
        for i in range(4)
    ]
    simple = chain_ladder(hand_triangle("paid"), average=Average.SIMPLE)
    latest_two = chain_ladder(hand_triangle("paid"), n_diagonals=2)
    assert isinstance(simple, ChainLadder) and isinstance(latest_two, ChainLadder)
    factors = [
        ["Volume-weighted (the default)", *[number(float(f)) for f in chain.factors]],
        ["Simple average", *[number(float(f)) for f in simple.factors]],
        ["Latest two diagonals", *[number(float(f)) for f in latest_two.factors]],
    ]
    ages = [f"{a}-{b}" for a, b in zip(AGES[:-1], AGES[1:], strict=True)]
    first, second, third = (float(f) for f in chain.factors)
    return "\n\n".join(
        [
            "The paid triangle of the hand fixture (cumulative, annual origins, ages in months):",
            triangle_table(hand_triangle("paid"), ORIGINS, AGES),
            "Link ratios $F_{i,j} = C_{i,j+1} / C_{i,j}$:",
            table(["Origin", *[f"{x} months" for x in ages]], ratios),
            "The volume-weighted factor of a column divides the sum of the later cells by the sum "
            "of the earlier cells of the origins that have both. For the first column "
            f"$(170 + 210 + 190) / (90 + 110 + 100) = 570 / 300 = {number(first)}$; "
            f"the second $(200 + 256) / (170 + 210) = {number(second)}$; "
            f"the third $220 / 200 = {number(third)}$. The averages side by side:",
            table(["Average", *[f"{x} months" for x in ages]], factors),
            "Cumulative factors to ultimate with the tail factor 1.0, and the ultimates:",
            per_origin(
                ["Latest paid", "CDF", "Ultimate", "Unpaid"],
                [chain.latest, chain.cdf_at_latest, chain.ultimate, chain.reserve],
            ),
            f"The total ultimate is {number(float(chain.ultimate.sum()), 2)} and the total unpaid "
            f"{number(float(chain.reserve.sum()), 2)} (latest paid "
            f"{number(float(chain.latest.sum()), 0)}). "
            "The test suite checks every number of this example against "
            "`tests/fixtures/hand/expected.yaml`.",
        ]
    )


def bf_on(measure: str) -> tuple[ChainLadder, BornhuetterFerguson]:
    chain = fitted(hand_triangle(measure))
    bf = bornhuetter_ferguson(chain, PREMIUM, PRIOR)
    assert isinstance(bf, BornhuetterFerguson)
    return chain, bf


def mt03() -> str:
    chain, bf = bf_on("incurred")
    return "\n\n".join(
        [
            "The incurred triangle of the hand fixture (paid plus case reserve) with earned "
            f"premium {', '.join(number(float(p), 0) for p in PREMIUM)} for the four origins, "
            f"and a prior loss ratio of {number(PRIOR, 2)}:",
            triangle_table(hand_triangle("incurred"), ORIGINS, AGES),
            "The chain ladder on this triangle gives the cumulative factors "
            f"{', '.join(number(float(c)) for c in chain.cdf)} for ages 12 to 48 months. "
            "Per origin:",
            per_origin(
                [
                    "Premium",
                    "Prior ultimate",
                    "Unreported share q",
                    "Latest",
                    "BF ultimate",
                    "Chain ladder",
                ],
                [
                    bf.premium,
                    bf.prior_ultimate,
                    bf.percent_unreported,
                    bf.latest,
                    bf.ultimate,
                    chain.ultimate,
                ],
            ),
            f"For 2024: $q = 1 - 1/{number(float(chain.cdf_at_latest[3]))} = "
            f"{number(float(bf.percent_unreported[3]))}$, prior ultimate "
            f"${number(PRIOR, 2)} \\times {number(float(PREMIUM[3]), 0)} = "
            f"{number(float(bf.prior_ultimate[3]), 0)}$, so the ultimate is "
            f"${number(float(bf.latest[3]), 0)} + {number(float(bf.percent_unreported[3]))} "
            f"\\times {number(float(bf.prior_ultimate[3]), 0)} = {number(float(bf.ultimate[3]))}$. "
            f"The total BF ultimate is {number(float(bf.ultimate.sum()), 2)} against "
            f"{number(float(chain.ultimate.sum()), 2)} for the chain ladder.",
        ]
    )


def mt04() -> str:
    sections: list[str] = []
    ratio: dict[str, float] = {}
    for measure in ("incurred", "paid"):
        chain = fitted(hand_triangle(measure))
        cc = cape_cod(chain, PREMIUM)
        assert isinstance(cc, CapeCod)
        ratio[measure] = cc.expected_loss_ratio
        sections += [
            f"On the {measure} triangle:",
            per_origin(
                ["Premium", "CDF", "Used-up premium", "Latest", "Cape Cod ultimate"],
                [PREMIUM, chain.cdf_at_latest, cc.used_up_premium, cc.latest, cc.ultimate],
            ),
            f"Expected loss ratio: ${number(float(cc.latest.sum()), 0)} / "
            f"{number(float(np.nansum(cc.used_up_premium)), 2)} = "
            f"{number(cc.expected_loss_ratio)}$. Total ultimate "
            f"{number(float(cc.ultimate.sum()), 2)}.",
        ]
    return "\n\n".join(
        [
            "The hand fixture with earned premium "
            f"{', '.join(number(float(p), 0) for p in PREMIUM)}. No prior is given: the data "
            "provide it.",
            *sections,
            f"The incurred ratio, {number(ratio['incurred'])}, is close to the prior of "
            f"{number(PRIOR, 2)} that the Bornhuetter–Ferguson example assumes; the paid ratio, "
            f"{number(ratio['paid'])}, is lower: the two triangles carry different information "
            "and each gives its own ratio.",
        ]
    )


def mt05() -> str:
    chain = fitted(hand_triangle("incurred"))
    elr = expected_loss_ratio(PREMIUM, PRIOR, chain.latest)
    assert isinstance(elr, ExpectedLossRatio)
    return "\n\n".join(
        [
            f"Earned premium {', '.join(number(float(p), 0) for p in PREMIUM)} and an expected "
            f"loss ratio of {number(PRIOR, 2)}; the incurred amounts are those of the hand "
            "fixture.",
            per_origin(
                [
                    "Premium",
                    "Expected ultimate",
                    "Incurred to date",
                    "IBNR",
                    "Chain ladder ultimate",
                ],
                [elr.premium, elr.ultimate, elr.incurred, elr.ibnr, chain.ultimate],
            ),
            "The two oldest origins show a negative IBNR "
            f"({number(float(elr.ibnr[0]), 2)} and {number(float(elr.ibnr[1]), 2)}): they have "
            f"already incurred more than {number(PRIOR * 100, 0)} per cent of premium, and the "
            "method ignores that. The "
            "platform flags this and the note's advice stands: use the method only for the "
            "newest origins.",
        ]
    )


def mt06() -> str:
    benchmark = load_benchmark("genins")
    cumulative = np.array(
        [[np.nan if v is None else v for v in row] for row in benchmark["triangle"]["values"]]
    )
    result = mack(cumulative)
    assert isinstance(result, Mack)
    origins = [str(o) for o in benchmark["triangle"]["origins"]]
    rows = [
        [
            origins[i],
            number(float(result.reserve[i]), 0),
            number(float(result.standard_error[i]), 0),
            number(float(result.coefficient_of_variation[i]), 3),
        ]
        for i in range(1, len(origins))
    ]
    rows.append(
        [
            "Total",
            number(result.total_reserve, 0),
            number(result.total_standard_error, 0),
            number(result.total_coefficient_of_variation, 3),
        ]
    )
    _, total = result.ranges()
    assert total is not None
    sigma = ", ".join(number(float(s), 1) for s in result.sigma_squared)
    return "\n\n".join(
        [
            "The 4 x 4 hand fixture is too small for the Mack model: it needs variance estimates "
            "from at least three development columns that have two or more link ratios, and the "
            "hand triangle has two such columns. The example therefore uses the 10 x 10 "
            "GenIns triangle (Taylor and Ashe, 1983, the triangle of Mack, 1993) from "
            "`tests/benchmarks/genins/`, whose standard errors the tests compare with the "
            "chainladder package to six significant figures.",
            "Reserve (chain-ladder ultimate minus latest cumulative), Mack standard error and "
            "coefficient of variation per origin (origin 2001 is fully developed):",
            table(["Origin", "Reserve", "Standard error", "CV"], rows),
            f"Variance parameters $\\hat\\sigma^2_j$ by column: {sigma} (the last is extrapolated "
            "with the rule of the specification).",
            "Lognormal step for the total: "
            f"$\\sigma^2 = \\ln(1 + ({number(total.standard_error, 0)} / "
            f"{number(total.reserve, 0)})^2) = {number(total.sigma**2, 5)}$ and "
            f"$\\mu = \\ln R - \\sigma^2/2 = {number(total.mu, 4)}$. The percentiles of the total "
            "reserve:",
            table(
                ["Percentile", "Total reserve"],
                [[f"{p:.1%}", number(v, 0)] for p, v in total.percentiles.items()],
            ),
            f"Value at risk at {total.var_level:.1%}: {number(total.value_at_risk, 0)}. "
            f"Tail value at risk at {total.tvar_level:.0%}: {number(total.tail_value_at_risk, 0)}. "
            "These two use the lognormal approximation, which the report labels as such.",
        ]
    )


def adjusted_paid(index: dict[int, float]) -> np.ndarray:
    """The hand paid triangle restated to prices of the last year end: each year's payments
    are taken at the index of that year end (the platform uses the month of each payment)."""
    paid = hand_triangle("paid")
    increments = paid.copy()
    increments[:, 1:] = paid[:, 1:] - paid[:, :-1]
    adjusted = np.full_like(paid, np.nan)
    for i, origin in enumerate(int(o) for o in ORIGINS):
        running = 0.0
        for j in range(4):
            if np.isnan(paid[i, j]):
                break
            running += increments[i, j] * index[2024] / index[origin + j]
            adjusted[i, j] = running
    return adjusted


def mt07() -> str:
    growth = 0.20
    future = 0.20
    index = {year: 100.0 * (1 + growth) ** (year - 2021) for year in range(2021, 2025)}
    nominal = hand_triangle("paid")
    adjusted = adjusted_paid(index)
    plain = fitted(nominal)
    result = inflation_adjusted_chain_ladder(
        adjusted,
        nominal_paid=plain.latest,
        cut_off=CUT_OFF,
        development_months=12,
        future_inflation=future,
        nominal=nominal,
    )
    assert isinstance(result, InflationAdjusted)
    assert result.nominal_unpaid is not None and result.nominal_ultimate is not None
    assert result.nominal_factors is not None
    ages = [f"{a}-{b}" for a, b in zip(AGES[:-1], AGES[1:], strict=True)]
    return "\n\n".join(
        [
            "An illustration, not data: the paid triangle of the hand fixture is read as nominal "
            f"amounts and the price index is assumed to grow {number(growth * 100, 0)} per cent a "
            "year, with year-end values "
            f"{', '.join(f'{y}: {number(v, 1)}' for y, v in index.items())}. To keep the "
            "arithmetic by hand, each year's payments are taken at the index of that year end; "
            "the platform uses the month of each payment (CV02).",
            "Each cell is the sum of its incremental payments times "
            "$I(2024)/I(\\text{year paid})$. "
            "Paid triangle at 2024 prices:",
            triangle_table(adjusted, ORIGINS, AGES),
            "Age-to-age factors, nominal against adjusted (the inflation of the later "
            "development years is gone from the adjusted ones):",
            table(
                ["Basis", *[f"{x} months" for x in ages]],
                [
                    ["Nominal", *[number(float(f)) for f in result.nominal_factors]],
                    ["Adjusted", *[number(float(f)) for f in result.chain.factors]],
                ],
            ),
            f"Ultimate at 2024 prices, and with a future inflation assumption of "
            f"{number(future * 100, 0)} per cent a year (each future payment re-inflated from the "
            "middle of its development year):",
            per_origin(
                [
                    "Paid at 2024 prices",
                    "Ultimate at 2024 prices",
                    "Unpaid at 2024 prices",
                    "Nominal unpaid",
                    "Nominal ultimate",
                    "Nominal chain ladder ultimate",
                ],
                [
                    result.chain.latest,
                    result.ultimate_at_value_date_prices,
                    result.unpaid_at_value_date_prices,
                    result.nominal_unpaid,
                    result.nominal_ultimate,
                    plain.ultimate,
                ],
            ),
            "The nominal chain ladder carries the past inflation into the future payments "
            "implicitly; the adjusted method makes the inflation an explicit and changeable "
            "assumption.",
        ]
    )


def robust_example() -> tuple[pl.DataFrame, list[float]]:
    logs = [float(y) for y in range(1, 31)] + [60.0]
    day = date(2024, 1, 31)
    frame = pl.DataFrame(
        {
            "claim_id": [f"C{k:03d}" for k in range(len(logs))],
            "valuation_date": [day] * len(logs),
            "paid_to_date": [math.exp(y) for y in logs],
            "case_reserve": [0.0] * len(logs),
            "currency": ["TRY"] * len(logs),
            SOURCE_ROW: list(range(2, len(logs) + 2)),
        },
        schema_overrides={"valuation_date": pl.Date},
    )
    return frame, logs


def mt08() -> str:
    frame, logs = robust_example()
    result = robust_z_flags(frame, None, {"TRY": 1.0}, variables=("paid_flow",))
    y = np.array(logs)
    median = float(np.median(y))
    mad = float(np.median(np.abs(y - median)))
    scores = result.scores.sort("claim_id")
    z = {int(k): float(v) for k, v in enumerate(scores["z"])}
    flag = result.flags.row(0, named=True)
    return "\n\n".join(
        [
            "The fixture of the MT08 specification: 31 payments of one group whose logarithms "
            "are the whole numbers 1 to 30 and one payment whose logarithm is 60 (a payment of "
            "$e^{60}$ amid payments of $e^1$ to $e^{30}$; the numbers are chosen for easy "
            "arithmetic, not for realism).",
            table(
                ["Quantity", "Value"],
                [
                    ["Median of the log values", number(median, 2)],
                    ["Median absolute deviation (MAD)", number(mad, 2)],
                    ["z of the payment with log 1", number(z[0], 4)],
                    ["z of the payment with log 30", number(z[29], 4)],
                    ["z of the payment with log 60", number(z[30], 4)],
                    ["Threshold", number(flag["threshold"], 1)],
                ],
            ),
            f"$z = 0.6745 \\times (60 - {number(median, 0)}) / {number(mad, 0)} = "
            f"{number(z[30], 4)}$, above 3.5, so exactly one payment is flagged: claim "
            f"{flag['claim_id']}, source row {flag[SOURCE_ROW]}, with its z and the "
            "threshold in the flag's text. The next largest payment has a z of "
            f"{number(z[29], 2)}.",
        ]
    )


def mt09() -> str:
    rng = np.random.default_rng(7)
    n = 150
    data = {name: rng.normal(size=n) for name in FEATURES}
    data["log_incurred"][0] = 25.0  # one claim far from the rest
    features = pl.DataFrame(
        {"claim_id": [f"C{k:04d}" for k in range(n)], "segment": ["S"] * n, **data}
    )
    result = isolation_forest_flags(features, n_estimators=TREES)
    scores = result.scores.sort("score", descending=True)
    top = scores.head(3)
    rest = scores.tail(n - 1)
    median_rest = float(np.median(rest["score"].to_numpy()))
    flag = result.flags.row(0, named=True)
    return "\n\n".join(
        [
            f"{n} claims of one segment with the ten MT09 features drawn from a seeded standard "
            "normal distribution (seed 7), except that claim C0000 has a `log_incurred` of 25, "
            f"far outside the rest. The forest has {TREES} trees (the default is 200; fewer keep "
            "the docs check fast), every claim in every tree and seed 1.",
            table(
                ["Rank", "Claim", "Score", "Flagged"],
                [
                    [k + 1, row["claim_id"], number(float(row["score"]), 3), str(row["flagged"])]
                    for k, row in enumerate(top.iter_rows(named=True))
                ],
            ),
            f"The median score of the other {n - 1} claims is "
            f"{number(median_rest, 3)} (a score near 0.5 means “no more "
            "isolated than average”, near 1 means “easily isolated”). With "
            f"`contamination` 0.01 the top $\\lceil 0.01 \\times {n} \\rceil = "
            f"{math.ceil(0.01 * n)}$ "
            f"claims of the group are flagged: {', '.join(result.flags['claim_id'].to_list())}. "
            "The second one is flagged only because the rule always flags that share of the "
            f"group, not because it is far out (its score is {number(float(top['score'][1]), 3)}, "
            f"the outlier's {number(float(top['score'][0]), 3)}); the flag of the first reads: "
            f"“{flag['reason']}”.",
        ]
    )


LABELS = {
    Choice.CHAIN_LADDER: "chain ladder",
    Choice.BORNHUETTER_FERGUSON: "Bornhuetter–Ferguson",
}


def mt10() -> str:
    chain = fitted(hand_triangle("paid"))
    bf = bornhuetter_ferguson(chain, PREMIUM, PRIOR)
    assert isinstance(bf, BornhuetterFerguson)
    incurred_chain = fitted(hand_triangle("incurred"))
    incurred_maturity = float((1 / incurred_chain.cdf_at_latest).min())
    default = select_ultimates(chain, bf)
    override = select_ultimates(chain, bf, overrides={2: Choice.BORNHUETTER_FERGUSON})
    assert isinstance(default, Selection) and isinstance(override, Selection)

    def methods(selection: Selection) -> list[str]:
        return [LABELS[m] for m in selection.method]

    rows = [
        [
            ORIGINS[i],
            number(float(default.maturity[i]), 3),
            number(float(chain.ultimate[i]), 2),
            number(float(bf.ultimate[i]), 2),
            methods(default)[i],
            number(float(default.ultimate[i]), 2),
            methods(override)[i],
            number(float(override.ultimate[i]), 2),
        ]
        for i in range(4)
    ]
    return "\n\n".join(
        [
            "The paid triangle of the hand fixture, premium "
            f"{', '.join(number(float(p), 0) for p in PREMIUM)} and a prior loss ratio of "
            f"{number(PRIOR, 2)}. The maturity of an origin is $1/CDF$, the share of its ultimate "
            "that the triangle says has been paid. Origins below 0.5 take Bornhuetter–Ferguson. "
            "The platform selects on the incurred triangle, where even the youngest origin of "
            f"this fixture has a maturity of {number(incurred_maturity, 3)} and so keeps the chain "
            "ladder; the paid triangle is used here because it shows the switch. "
            "The last two columns show an override of origin 2023 to Bornhuetter–Ferguson, as a "
            "user would record it in the assumptions register:",
            table(
                [
                    "Origin",
                    "Maturity",
                    "Chain ladder",
                    "BF",
                    "Default choice",
                    "Default ultimate",
                    "With override",
                    "Ultimate with override",
                ],
                rows,
            ),
            "Reason recorded for 2024: " + default.why[3] + ". Reason for 2023 with the "
            "override: " + override.why[2] + ".",
        ]
    )


def ratios() -> str:
    chain = fitted(hand_triangle("incurred"))
    ultimate = chain.ultimate
    paid = hand_triangle("paid")
    paid_latest = fitted(paid).latest
    loss = ultimate / PREMIUM
    expense, commission = 0.08, 0.12
    rows = [
        [
            ORIGINS[i],
            number(float(PREMIUM[i]), 0),
            number(float(paid_latest[i]), 0),
            number(float(paid_latest[i] / PREMIUM[i]), 4),
            number(float(chain.latest[i]), 0),
            number(float(chain.latest[i] / PREMIUM[i]), 4),
            number(float(ultimate[i]), 2),
            number(float(loss[i]), 4),
            number(float(loss[i] + expense + commission), 4),
        ]
        for i in range(4)
    ]
    return "\n\n".join(
        [
            "Earned premium, paid and incurred of the hand fixture; the ultimate is the chain "
            "ladder on the incurred triangle (the default selection for these origins). The "
            "expense "
            "and commission ratios are not in the fixture: the example assumes "
            f"{number(expense, 2)} and {number(commission, 2)} for every origin to show the sum.",
            table(
                [
                    "Origin",
                    "Earned premium",
                    "Paid",
                    "Paid ratio",
                    "Incurred",
                    "Incurred ratio",
                    "Ultimate",
                    "Ultimate ratio",
                    "Combined ratio",
                ],
                rows,
            ),
            f"Trend: the ultimate loss ratio moves from {number(float(loss[0]), 4)} for 2021 to "
            f"{number(float(loss[-1]), 4)} for 2024, a change of "
            f"{number(float(loss[-1] - loss[0]) * 100, 1)} percentage points. The paid ratio of "
            "the "
            "newest origin looks low only because its claims are not yet paid; the ultimate "
            "ratio puts all origins on the same footing.",
        ]
    )


EXAMPLES = {
    "MT01-triangle-construction": mt01,
    "MT02-chain-ladder": mt02,
    "MT03-bornhuetter-ferguson": mt03,
    "MT04-cape-cod": mt04,
    "MT05-expected-loss-ratio": mt05,
    "MT06-mack": mt06,
    "MT07-inflation-adjusted-chain-ladder": mt07,
    "MT08-robust-z-score-flags": mt08,
    "MT09-isolation-forest-flags": mt09,
    "MT10-ultimate-selection": mt10,
    "RT01-loss-and-combined-ratios": ratios,
}


def block(name: str) -> str:
    return f"{BEGIN}\n\n{EXAMPLES[name]()}\n\n{END}"


def current(name: str) -> str | None:
    """The note as it should be, or None when it has no markers (a defect the test reports)."""
    path = NOTES / f"{name}.md"
    text = path.read_text(encoding="utf-8")
    if not BLOCK.search(text):
        return None
    return BLOCK.sub(lambda _: block(name), text, count=1)


def main(argv: Sequence[str]) -> int:
    write = "--write" in argv
    stale: list[str] = []
    for name in EXAMPLES:
        path = NOTES / f"{name}.md"
        wanted = current(name)
        if wanted is None:
            print(f"{path.name}: no worked-example markers")
            stale.append(name)
        elif wanted != path.read_text(encoding="utf-8"):
            stale.append(name)
            if write:
                path.write_text(wanted, encoding="utf-8", newline="\n")
                print(f"{path.name}: written")
            else:
                print(f"{path.name}: differs from the code; run `just notes`")
    return 0 if write or not stale else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
