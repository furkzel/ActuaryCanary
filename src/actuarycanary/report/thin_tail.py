"""What stands behind the last development factors and the tail, on the page of one line
(A1b, records 0776 and 0777): the factors the rule set to 1.000, the tail used and where it
comes from, the share of open claims, the curves MT14 fitted and what the report does not do.

The numbers come from the run's own results and from `sensitivity.csv` (variant
`thin_average`, `tail_fitted`); nothing here chooses an assumption.
"""

from collections.abc import Mapping
from typing import Any

import numpy as np
import polars as pl

from actuarycanary.methods.assumptions import DEFAULT_WHO
from actuarycanary.methods.chain_ladder import ChainLadder, Skipped
from actuarycanary.methods.judgement import SETTINGS_WHO
from actuarycanary.methods.tail import CurveFit, TailFit
from actuarycanary.modules.reserving import SELECTION_MEASURE, GroupReserving
from actuarycanary.modules.runner import AnalysisResult
from actuarycanary.report import numbers
from actuarycanary.report.findings import Fact
from actuarycanary.report.frames import of_line, table, value
from actuarycanary.report.language import t
from actuarycanary.report.sensitivity import SENSITIVITY_NAME
from actuarycanary.structures.triangles import MEASURES

TAIL_OPEN_SHARE_LIMIT = 0.10  # a default tail with this share of claims open is worth a sentence
TAIL_FITTED_LIMIT = 0.05  # ... or with fitted curves that move the selected IBNR this much
CURVE_LABELS = {"exponential_decay": "exponential decay", "inverse_power": "inverse power"}


def _scope(group: GroupReserving, measure: str) -> str:
    return "/".join((*group.group, measure))


def open_claim_share(
    analysis: AnalysisResult | None, group: GroupReserving
) -> tuple[float | None, int, int, str]:
    """(open share of the claims reported, open, reported, reason when unknown) of the line at
    the cut-off, from the claim counts CL04."""
    from actuarycanary.report.facts import find_result

    if analysis is None:
        return None, 0, 0, "the run has no claim counts"
    found = find_result(analysis, "CL04", ("segment", "line"))
    if found is None or found.frame is None or not found.frame.height:
        return None, 0, 0, "the run has no claim counts (CL04) for this line"
    rows = of_line(found.frame, *group.group[:2])
    counts = {str(r["count_type"]): value(r["value"]) for r in rows if "count_type" in r}
    reported, open_ = counts.get("reported"), counts.get("open")
    if reported is None or open_ is None:
        return None, 0, 0, "the claim counts of this line do not state the open claims"
    if reported <= 0:
        return None, 0, int(reported), "no claim is reported on this line"
    return open_ / reported, int(open_), int(reported), ""


def tail_source(group: GroupReserving, measure: str) -> tuple[str, bool]:
    """(where the tail used comes from, whether it is the MT02 default 1.000 of the platform)."""
    scope = _scope(group, measure)
    entry = next(
        (
            e
            for e in group.assumptions
            if e.method == "MT02" and e.name == "tail_factor" and e.scope == scope
        ),
        None,
    )
    if entry is None or entry.who == DEFAULT_WHO:
        return t("MT02 default"), True
    if entry.who == SETTINGS_WHO:
        return t("run setting"), False
    if entry.why.startswith("MT14"):
        return t("assumptions register: MT14 curve selected by {who}", who=entry.who), False
    return t("assumptions register, entered by {who}", who=entry.who), False


def _fitted(fit: TailFit | Skipped | None) -> str:
    if fit is None:
        return numbers.EMPTY
    if isinstance(fit, Skipped):
        return t("not fitted: {reason}", reason=fit.reason)
    parts = [
        f"{t(CURVE_LABELS.get(curve.value, curve.value))} {numbers.factor(found.tail_factor)}"
        for curve, found in fit.fits.items()
        if isinstance(found, CurveFit)
    ]
    return "; ".join(parts) if parts else numbers.EMPTY


def _row(tables: Mapping[str, pl.DataFrame], group: GroupReserving, variant: str) -> dict | None:
    rows = of_line(table(tables, SENSITIVITY_NAME), *group.group[:2])
    return next((r for r in rows if r["variant"] == variant), None)


def thin_effect(tables: Mapping[str, pl.DataFrame], group: GroupReserving) -> dict | None:
    """The `thin_average` row of the line: the selected unpaid with the rule and with the
    average of every column the rule replaced."""
    found = _row(tables, group, "thin_average")
    if found is None or value(found["value"]) is None:
        return None
    return found


def thin_factors(tables: Mapping[str, pl.DataFrame], group: GroupReserving) -> dict | None:
    """The factors the rule replaced on this line, each with the average it replaced, and the
    change of the selected unpaid with the averages instead. None when the rule replaced none."""
    notes: list[str] = []
    for measure in MEASURES:
        chain = group.chain_ladder.get(measure)
        if not isinstance(chain, ChainLadder):
            continue
        ages = group.triangles[measure].ages
        for j in np.flatnonzero(chain.replaced):
            notes.append(
                t(
                    "{measure}: the factor {column} rests on {n} link ratio and is 1.000; the "
                    "average it replaced is {average}.",
                    measure=t(measure),
                    column=f"{ages[int(j)]}-{ages[int(j) + 1]}",
                    n=int(chain.n_ratios[j]),
                    average=numbers.factor(float(chain.averages[j])),
                )
            )
    if not notes:
        return None
    found = thin_effect(tables, group)
    effect = ""
    if found is not None:
        effect = t(
            "With the averages instead of 1.000 the selected unpaid of this line would be "
            "{value} instead of {base} ({change}).",
            value=numbers.amount(value(found["value"])),
            base=numbers.amount(value(found["base"])),
            change=numbers.change_ratio(value(found["relative"])),
        )
    return {
        "notes": notes,
        "effect": effect,
        "footnote": t(
            "A development factor that rests on fewer link ratios than the setting "
            "min_origins_per_factor of the run (default 2) is set to 1.000 instead of the "
            "average; a factor selected in the assumptions register wins over the rule. The "
            "average stays in the table of averages; the change is the variant thin_average of "
            "sensitivity.csv ({spec}).",
            spec="MT02",
        ),
    }


def tail_box(
    tables: Mapping[str, pl.DataFrame],
    group: GroupReserving,
    analysis: AnalysisResult | None,
    effect: dict[str, Any] | None,
) -> dict[str, Any]:
    """The tail of every triangle of the line in one place."""
    fits = group.tier_b.tails if group.tier_b is not None else {}
    rows: list[dict[str, str]] = []
    defaults: list[tuple[str, float, int]] = []
    for measure in MEASURES:
        chain = group.chain_ladder.get(measure)
        if not isinstance(chain, ChainLadder):
            continue
        source, is_default = tail_source(group, measure)
        if is_default:
            defaults.append((measure, chain.tail_factor, group.triangles[measure].ages[-1]))
        rows.append(
            {
                "measure": t(measure),
                "tail": numbers.factor(chain.tail_factor),
                "source": source,
                "fitted": _fitted(fits.get(measure)),
            }
        )
    notes: list[str] = []
    if defaults:
        measures = "/".join(t(m) for m, _, _ in defaults)
        notes.append(
            t(
                "The tail factor of the {measures} triangle is the MT02 default {tail}: no "
                "development after the last age ({age} months). It is not an estimate of the "
                "development that is still to come.",
                measures=measures,
                tail=numbers.factor(defaults[0][1]),
                age=defaults[0][2],
            )
        )
    share, open_, reported, reason = open_claim_share(analysis, group)
    if share is not None:
        notes.append(
            t(
                "{share} of the claims reported on this line are open at the cut-off "
                "({open} of {reported}).",
                share=numbers.ratio(share),
                open=numbers.count(open_),
                reported=numbers.count(reported),
            )
        )
    else:
        notes.append(
            t(
                "The share of open claims at the cut-off is not available: {reason}.",
                reason=t(reason),
            )
        )
    if effect:
        notes.append(
            t(
                "With the tail of the chosen curves the selected IBNR would be {value} instead "
                "of {base} ({change}).",
                value=effect["value"],
                base=effect["base"],
                change=effect["change"],
            )
        )
    elif not any(row["fitted"] != numbers.EMPTY for row in rows):
        notes.append(t("No tail curve was fitted on this line (MT14)."))
    notes.append(
        t(
            "The report does not choose between the tail used and the fitted curves. The tail "
            "is set in the assumptions register (MT02 tail_factor, or MT14 selected_curve for a "
            "fitted curve)."
        )
    )
    return {
        "rows": rows,
        "notes": notes,
        "footnote": t(
            "Tail factors of the chain ladder ({mt02}) and the curves fitted by {mt14}; rows of "
            "assumptions.csv and tier_b_parameters.csv. The claim counts are CL04.",
            mt02="MT02",
            mt14="MT14",
        ),
    }


def add_thin_tail_facts(
    facts: dict[str, Fact],
    tables: Mapping[str, pl.DataFrame],
    group: GroupReserving,
    analysis: AnalysisResult | None,
) -> None:
    """The facts of the rules KF42 (a replaced factor moved the unpaid) and KF43 (a default
    tail on a line whose claims are open or whose fitted curves move the IBNR)."""
    replaced = []
    for measure in MEASURES:
        chain = group.chain_ladder.get(measure)
        if isinstance(chain, ChainLadder):
            ages = group.triangles[measure].ages
            replaced += [
                f"{measure} {ages[int(j)]}-{ages[int(j) + 1]}"
                for j in np.flatnonzero(chain.replaced)
            ]
    facts["thin_factor_count"] = Fact(len(replaced), "count")
    if replaced:
        facts["thin_factor_list"] = Fact(", ".join(replaced), "text")
    found = thin_effect(tables, group)
    if found is not None:
        relative = value(found["relative"])
        if relative is not None:
            facts["thin_unpaid_change_size"] = Fact(abs(relative), "ratio")
            facts["thin_unpaid_direction"] = Fact(t("more") if relative > 0 else t("less"), "text")
            facts["thin_unpaid_base"] = Fact(value(found["base"]) or 0.0, "amount")
            facts["thin_unpaid_average"] = Fact(value(found["value"]) or 0.0, "amount")

    chain = group.chain_ladder.get(SELECTION_MEASURE)
    if not isinstance(chain, ChainLadder):
        return
    _, is_default = tail_source(group, SELECTION_MEASURE)
    facts["tail_default"] = Fact(1 if is_default else 0, "count")
    share, _, _, _ = open_claim_share(analysis, group)
    if share is not None:
        facts["open_claim_share"] = Fact(share, "ratio")
    fitted = _row(tables, group, "tail_fitted")
    change = value(fitted["relative"]) if fitted is not None else None
    reasons = []
    if share is not None and share >= TAIL_OPEN_SHARE_LIMIT:
        reasons.append(
            t("{share} of its claims are open at the cut-off", share=numbers.ratio(share))
        )
    if change is not None and abs(change) >= TAIL_FITTED_LIMIT:
        reasons.append(
            t(
                "the tail of the curves MT14 fitted would change the selected IBNR by {change}",
                change=numbers.ratio(abs(change)),
            )
        )
    facts["tail_default_concern"] = Fact(len(reasons) if is_default else 0, "count")
    facts["tail_default_reasons"] = Fact("; ".join(reasons), "text")
