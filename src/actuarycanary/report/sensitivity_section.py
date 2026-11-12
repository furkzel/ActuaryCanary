"""The sensitivity tables of the reserving page (record 0343): per line, the reserve under each
variant of `sensitivity.csv` against the run's own, with the change. Variants of the discount
curve belong to the discounted basis, the others to the nominal one."""

from collections.abc import Callable, Mapping
from typing import Any

import polars as pl

from actuarycanary.report import numbers
from actuarycanary.report.frames import table, text, value
from actuarycanary.report.language import t
from actuarycanary.report.sensitivity import (
    CURVE_STEP,
    FACTOR_STEP,
    INFLATION_STEP,
    SENSITIVITY_NAME,
    TAIL_STEP,
)


def sensitivity_page(
    tables: Mapping[str, pl.DataFrame], spec: Callable[..., str]
) -> dict[str, Any] | None:
    frame = table(tables, SENSITIVITY_NAME)
    if not frame.height:
        return None
    blocks: dict[str, list[dict[str, Any]]] = {}
    for r in frame.to_dicts():
        blocks.setdefault(str(r["value_basis"]), []).append(
            {
                "line": f"{r['segment']} · {r['line']}",
                "assumption": t(str(r["assumption"])),
                "change": t(str(r["change"])),
                "quantity": t(str(r["quantity"])),
                "base": numbers.amount(value(r["base"])),
                "value": numbers.amount(value(r["value"])),
                "difference": numbers.change_amount(value(r["difference"])),
                "relative": numbers.change_ratio(value(r["relative"])),
                "note": text(r["note"]),
            }
        )
    # a basis on which no variant could be computed (no curve: no discounted figures) shows its
    # reason instead of an empty table that no switch could reveal
    shown = {k: v for k, v in blocks.items() if any(r["value"] != numbers.EMPTY for r in v)}
    reasons = sorted(
        {r["note"] for k, v in blocks.items() if k not in shown for r in v if r["note"]}
    )
    return {
        "blocks": [{"basis": basis, "rows": rows} for basis, rows in shown.items()],
        "reasons": reasons,
        "footnote": t(
            "Each variant reruns the methods of this run with one assumption changed "
            "({specs}): every selected development factor f moved to 1 + (f − 1)(1 ± "
            "{factor}), the tail factor raised by {tail} or replaced by the curve MT14 "
            "fitted, the average put back for a development factor that the rule of the run "
            "set to 1.000, the future inflation of MT07 moved by {inflation} (no stated inflation "
            "is 0, value-date prices), the zero rates of the discount curve moved by {curve}. "
            "Rows of sensitivity.csv; the steps are in the settings (report.sensitivity).",
            specs=spec("MT02", "MT10", "MT14", "MT07", "RS04"),
            factor=numbers.ratio(FACTOR_STEP),
            tail=numbers.factor(TAIL_STEP),
            inflation=numbers.ratio(INFLATION_STEP),
            curve=numbers.ratio(CURVE_STEP),
        ),
    }


__all__ = ["sensitivity_page"]
