"""The M10 page (ledger reconciliation) and the facts of its finding rules (RP01 1.6.0, record
0425): the headline (material gaps, the largest, the unmapped share), the gaps by class and by
month with the materiality marked, the trend of the gap per class, the unmapped accounts with
their balances, and the profile in use with its state, signs and balance kinds."""

from datetime import date
from typing import Any

import polars as pl

from actuarycanary.ledger import causes as cause_codes
from actuarycanary.modules.ledger_reconciliation import NO_CAUSE, PROPOSED, LedgerTables
from actuarycanary.report import charts, numbers
from actuarycanary.report.facts import FactSet, _put
from actuarycanary.report.language import t

MONTHS = 18  # months of the gap matrix
LISTED = 15  # material gaps listed on the page; all are in reconciliation.csv
MATRIX_ROWS = 40  # entity-class pairs of the matrix
CAUSE_WORDS = {
    cause_codes.CUT_OFF_TIMING: "cut-off timing",
    cause_codes.CURRENCY: "currency",
    cause_codes.IBNR_IN_OUTSTANDING: "IBNR in the ledger outstanding",
    cause_codes.UNMAPPED_ACCOUNT: "an unmapped account",
}
STATE_WORDS = {"proposed": "proposed, not confirmed"}


def cause_text(codes: str) -> str:
    """The suggested causes of a row as the report words them; always as a suggestion."""
    if not codes or codes == NO_CAUSE:
        return t("no cause suggested")
    return ", ".join(t(CAUSE_WORDS[c]) for c in codes.split("; "))


def state_text(label: str) -> str:
    if label == PROPOSED:
        return t("proposed, not confirmed")
    return t("confirmed on {date}", date=label.removeprefix("confirmed on "))


def _share(row: dict[str, Any]) -> str:
    return numbers.ratio(row["share"]) if row["share"] is not None else t("ledger amount zero")


def _month(day: date) -> str:
    return f"{day.year}-{day.month:02d}"


def _classes(tables: LedgerTables) -> list[dict[str, Any]]:
    rec = tables.reconciliation
    rows: list[dict[str, Any]] = []
    for account_class in sorted(rec["account_class"].unique().to_list()):
        part = rec.filter((pl.col("account_class") == account_class) & pl.col("gap").is_not_null())
        material = part.filter(pl.col("material"))
        largest = material.sort(pl.col("gap").abs(), descending=True).head(1)
        rows.append(
            {
                "account_class": account_class,
                "months": numbers.count(part.height),
                "material": numbers.count(material.height),
                "largest": numbers.amount(largest["gap"][0]) if largest.height else numbers.EMPTY,
                "largest_share": _share(largest.row(0, named=True))
                if largest.height
                else numbers.EMPTY,
                "state": t("reconciled"),
                "reason": "",
            }
        )
    for r in tables.not_reconciled.iter_rows(named=True):
        rows.append(
            {
                "account_class": r["account_class"],
                "months": numbers.EMPTY,
                "material": numbers.EMPTY,
                "largest": numbers.EMPTY,
                "largest_share": numbers.EMPTY,
                "state": t("not reconciled"),
                "reason": r["reason"],
            }
        )
    return rows


def _matrix(tables: LedgerTables, cut_off: date) -> dict[str, Any]:
    """The gap as a share of the ledger amount, month by month, for the entity-class pairs that
    have a material gap; a material cell is marked."""
    rec = tables.reconciliation.filter(pl.col("gap").is_not_null())
    pairs = (
        rec.filter(pl.col("material"))
        .select("entity", "account_class")
        .unique()
        .sort("entity", "account_class")
    )
    months = sorted(rec.filter(pl.col("period") <= cut_off)["period"].unique().to_list())[-MONTHS:]
    cells = rec.filter(pl.col("period").is_in(months))
    rows: list[dict[str, Any]] = []
    for pair in pairs.head(MATRIX_ROWS).iter_rows(named=True):
        part = cells.filter(
            (pl.col("entity") == pair["entity"])
            & (pl.col("account_class") == pair["account_class"])
        )
        by_month = {r["period"]: r for r in part.iter_rows(named=True)}
        row_cells = []
        for month in months:
            found = by_month.get(month)
            if found is None:
                row_cells.append({"text": numbers.EMPTY, "material": False})
            else:
                text = _share(found) if found["share"] is not None else numbers.amount(found["gap"])
                row_cells.append({"text": text, "material": bool(found["material"])})
        rows.append({"label": f"{pair['entity']} · {pair['account_class']}", "cells": row_cells})
    return {
        "months": [_month(m) for m in months],
        "rows": rows,
        "more": max(0, pairs.height - MATRIX_ROWS),
    }


def _largest(tables: LedgerTables, currency: str) -> list[dict[str, Any]]:
    material = tables.material.sort(pl.col("gap").abs(), descending=True).head(LISTED)
    return [
        {
            "entity": r["entity"],
            "account_class": r["account_class"],
            "month": _month(r["period"]),
            "platform": numbers.amount(r["platform_amount"]),
            "ledger": numbers.amount(r["ledger_amount"]),
            "gap": numbers.amount(r["gap"]),
            "share": _share(r),
            "causes": cause_text(r["suggested_causes"]),
            "evidence": r["cause_evidence"],
        }
        for r in material.iter_rows(named=True)
    ]


def _trend(tables: LedgerTables, figures: dict[str, Any]) -> str:
    """The gap of each class as a share of its ledger amount, month by month, over the entities."""
    rec = tables.reconciliation.filter(pl.col("gap").is_not_null())
    traces: list[dict[str, Any]] = []
    for account_class in sorted(rec["account_class"].unique().to_list()):
        part = (
            rec.filter(pl.col("account_class") == account_class)
            .group_by("period")
            .agg(
                pl.col("gap").sum().alias("gap"), pl.col("ledger_amount").abs().sum().alias("size")
            )
            .filter(pl.col("size") > 0)
            .sort("period")
        )
        if part.height < 2:
            continue
        traces.append(
            {
                "type": "scatter",
                "mode": "lines",
                "name": account_class,
                "x": [_month(d) for d in part["period"].to_list()],
                "y": [round(g / s, 6) for g, s in zip(part["gap"], part["size"], strict=True)],
                "line": {"width": 2},
                "hovertemplate": "%{fullData.name} %{x}: %{y:.2%}<extra></extra>",
            }
        )
    if not traces:
        return ""
    figures["ledger-gap-trend"] = {
        "data": traces,
        "layout": charts._layout(
            t("Gap between the platform and the ledger, by class and month"),
            t("Month"),
            t("Gap, share of the ledger amount"),
            xaxis={"title": {"text": t("Month")}, "type": "category", "nticks": 12},
            yaxis={"title": {"text": t("Gap, share of the ledger amount")}, "tickformat": ".1%"},
            showlegend=True,
            height=320,
        ),
    }
    return "ledger-gap-trend"


def _unmapped(tables: LedgerTables) -> list[dict[str, Any]]:
    return [
        {
            "entity": r["entity"],
            "account": r["account"],
            "name": r["account_name"] or numbers.EMPTY,
            "latest": _month(r["latest_period"]),
            "balance": numbers.amount(r["latest_balance"]),
            "largest": numbers.amount(r["largest_balance"]),
            "months": numbers.count(r["months_with_balance"]),
            "reason": r["reason"],
        }
        for r in tables.unmapped.iter_rows(named=True)
    ]


def _share_now(tables: LedgerTables) -> tuple[float | None, str, str]:
    """The largest unmapped share among the entities in their latest month, with the entity and
    the month."""
    share = tables.share.filter(pl.col("value").is_not_null())
    if share.height == 0:
        return None, "", ""
    latest = share.sort("period").group_by("entity", maintain_order=True).last()
    top = latest.sort("value", descending=True).row(0, named=True)
    return float(top["value"]), str(top["entity"]), _month(top["period"])


def ledger_page(
    tables: LedgerTables | None, cut_off: date, spec: Any, figures: dict[str, Any], currency: str
) -> dict[str, Any]:
    if tables is None:
        return {"available": False}
    material = tables.material
    largest = material.sort(pl.col("gap").abs(), descending=True).head(1)
    share, share_entity, share_month = _share_now(tables)
    settings = tables.settings
    ratio = numbers.ratio(settings.materiality_ratio)
    if settings.materiality_amount > 0:
        limit = t(
            "{ratio} of the ledger amount and {amount} {currency}",
            ratio=ratio,
            amount=numbers.amount(settings.materiality_amount),
            currency=currency,
        )
    else:
        limit = t("{ratio} of the ledger amount", ratio=ratio)
    return {
        "available": True,
        "material": numbers.count(material.height),
        "computed": numbers.count(tables.reconciliation["gap"].drop_nulls().len()),
        "largest": (
            t(
                "{amount} {currency} in {account_class} of {entity}, {month}",
                amount=numbers.amount(largest["gap"][0]),
                currency=currency,
                account_class=largest["account_class"][0],
                entity=largest["entity"][0],
                month=_month(largest["period"][0]),
            )
            if largest.height
            else numbers.EMPTY
        ),
        "unmapped_share": numbers.ratio(share),
        "unmapped_where": f"{share_entity}, {share_month}" if share is not None else "",
        "limit": limit,
        "profile": {
            "fingerprint": tables.fingerprint,
            "sha256": tables.sha256[:16],
            "state": state_text(tables.mapping),
            "proposed": tables.mapping == PROPOSED,
            "rules": [
                {
                    "pattern": r["pattern"],
                    "entity": r["entity"] or t("every entity"),
                    "account_class": r["account_class"],
                    "sign": f"{r['sign']:+d}",
                    "kind": t(r["balance_kind"]),
                }
                for r in tables.rules.iter_rows(named=True)
            ],
        },
        "classes": _classes(tables),
        "matrix": _matrix(tables, cut_off),
        "largest_gaps": _largest(tables, currency),
        "listed": numbers.count(min(LISTED, material.height)),
        "figure": _trend(tables, figures),
        "unmapped": _unmapped(tables),
        "notes": list(tables.notes),
        "footnote": t(
            "{currency}. Gap {fn01} is the platform's figure minus the mapped ledger amount per "
            "entity, class and month; it is material above {limit}. The share of the books no "
            "rule maps {fn02}. Causes are suggestions with their evidence, not findings of fact. "
            "Files: reconciliation.csv, unmapped_accounts.csv; the profile is "
            "ledger-{fingerprint}.yaml in the profiles folder ({cv12}).",
            currency=currency,
            fn01=spec("FN01"),
            fn02=spec("FN02"),
            cv12=spec("CV12"),
            limit=limit,
            fingerprint=tables.fingerprint,
        ),
    }


def add_ledger_facts(facts: FactSet, tables: LedgerTables | None) -> None:
    """Facts of KF47 to KF49: the material gaps and the largest, the largest unmapped share, and
    whether the profile in use is only proposed. A run without M10 has none."""
    if tables is None:
        return
    rec = tables.reconciliation
    material = tables.material
    _put(facts, "ledger_profile_proposed", float(tables.mapping == PROPOSED), "count")
    _put(facts, "ledger_profile_fingerprint", tables.fingerprint, "text")
    share, entity, month = _share_now(tables)
    if share is not None:
        _put(facts, "ledger_unmapped_share", share, "ratio")
        _put(facts, "ledger_unmapped_entity", entity, "text")
        _put(facts, "ledger_unmapped_month", month, "text")
        names = tables.unmapped.filter(pl.col("entity") == entity)["account"].to_list()
        _put(facts, "ledger_unmapped_accounts", ", ".join(names) or numbers.EMPTY, "text")
    computed = rec["gap"].drop_nulls().len()
    if not computed:
        return
    _put(facts, "ledger_material_gaps", float(material.height), "count")
    _put(facts, "ledger_gap_rows", float(computed), "count")
    if not material.height:
        return
    counts = (
        material.group_by("account_class").len().sort("len", descending=True, maintain_order=True)
    )
    _put(
        facts,
        "ledger_gap_classes",
        ", ".join(f"{r['account_class']} {r['len']}" for r in counts.iter_rows(named=True)),
        "text",
    )
    top = material.sort(pl.col("gap").abs(), descending=True).row(0, named=True)
    _put(facts, "ledger_largest_gap", abs(top["gap"]), "amount")
    _put(facts, "ledger_largest_gap_class", top["account_class"], "text")
    _put(facts, "ledger_largest_gap_entity", top["entity"], "text")
    _put(facts, "ledger_largest_gap_month", _month(top["period"]), "text")
    size = (
        t("{share} of the ledger amount", share=numbers.ratio(top["share"]))
        if top["share"] is not None
        else t("the ledger amount is zero")
    )
    _put(facts, "ledger_largest_gap_share", size, "text")
    _put(facts, "ledger_largest_gap_cause", cause_text(top["suggested_causes"]), "text")
