"""The data rules of the feeds added after version 1.0 (spec/data/), decided on the files alone.

``check_folder`` in ``check.py`` calls ``check_later_feeds`` after the rules of the first six
feeds. Layout is undone with the truth logs, as there. Each violation names its rule ID; the
severity of the rule in the specification is in ``severity``. A rule that needs a feed which is
not in the folder is skipped, as the specification says.
"""

import re
from typing import Any

import polars as pl

from actuarycanary.synthetic.check import Violation, _class_ok, _Reader
from actuarycanary.synthetic.ledger import chart

CURRENCY = re.compile(r"^[A-Z]{3}$")
TERMINAL = ("DEATH", "SURRENDER", "LAPSE", "MATURITY", "TRANSFER_OUT")
EXIT_STATUS = {
    "DEATH": "DEATH_CLAIM",
    "SURRENDER": "SURRENDERED",
    "LAPSE": "LAPSED",
    "MATURITY": "MATURED",
    "TRANSFER_OUT": "TRANSFERRED_OUT",
}
LATER_FEEDS = (
    "reinsurance_treaties",
    "reinsurance_transactions",
    "recoveries",
    "ledger",
    "interest_rates",
    "life_in_force",
    "life_events",
    "fund_flows",
)


def check_later_feeds(
    reader: _Reader, tables: dict[str, dict[str, pl.DataFrame] | None]
) -> list[Violation]:
    """Violations of the rules DV-RTY, DV-RTR, DV-RCV, DV-LDG, DV-IRT, DV-LIF, DV-LEV, DV-FFL."""
    later = {feed: reader.read(feed) for feed in LATER_FEEDS}
    one = {feed: sheets[feed] for feed, sheets in later.items() if sheets is not None}
    found: list[Violation] = []
    if "reinsurance_treaties" in one:
        found += _treaties(reader, one["reinsurance_treaties"], tables)
    if "reinsurance_transactions" in one:
        found += _transactions(reader, one["reinsurance_transactions"], one, tables)
    if "recoveries" in one:
        found += _recoveries(reader, one["recoveries"], tables)
    if "ledger" in one:
        found += _ledger(reader, one["ledger"])
    if "interest_rates" in one:
        found += _rates(reader, one["interest_rates"])
    if "life_in_force" in one:
        found += _life(reader, one["life_in_force"], one.get("life_events"))
    if "life_events" in one:
        found += _events(reader, one["life_events"], one.get("life_in_force"))
    if "fund_flows" in one:
        found += _flows(reader, one["fund_flows"], one.get("life_in_force"), one.get("life_events"))
    return [_with_severity(reader, v) for v in found]


def _with_severity(reader: _Reader, violation: Violation) -> Violation:
    for spec in reader.spec.values():
        for rule in spec.get("validation", []):
            if rule["id"] == violation.rule:
                return Violation(
                    violation.rule,
                    violation.file,
                    violation.count,
                    f"[{rule['severity']}] {violation.detail}",
                )
    return violation


def severity_of(violation: Violation) -> str:
    """BLOCKING, WARNING or INFO, as the specification gives it for the rule."""
    match = re.match(r"\[(\w+)\]", violation.detail)
    return match.group(1) if match else "WARNING"


# --- helpers ---------------------------------------------------------------------------


def _count(rule: str, file: str, mask: Any, detail: str) -> list[Violation]:
    """A violation of `rule` when a mask has true cells (or a count is above zero)."""
    n = int(mask.sum()) if isinstance(mask, pl.Series) else int(mask)
    return [Violation(rule, file, n, detail)] if n else []


def _missing(frame: pl.DataFrame, columns: list[str]) -> pl.Series:
    mask = pl.Series([False] * frame.height)
    for name in columns:
        mask = mask | frame[name].is_null()
    return mask


def _bad_currency(column: pl.Series) -> pl.Series:
    return column.map_elements(
        lambda v: v is None or not CURRENCY.match(str(v)), return_dtype=pl.Boolean, skip_nulls=False
    )


def _unmapped(reader: _Reader, feed: str, frame: pl.DataFrame, fields: list[str]) -> int:
    count = 0
    for name in fields:
        if name not in frame.columns:
            continue
        classes = [
            c
            for f in reader.spec[feed]["fields"]
            if f["name"] == name
            for c in f.get("classes", [])
        ]
        present = frame[name].is_not_null()
        ok = _class_ok(reader, feed, name, frame[name], classes)
        count += int((present & ~ok).sum())
    return count


def _month_end(column: pl.Series) -> pl.Series:
    return column.dt.offset_by("1d").dt.day() == 1


# --- reinsurance --------------------------------------------------------------------------


def _treaties(
    reader: _Reader, t: pl.DataFrame, tables: dict[str, dict[str, pl.DataFrame] | None]
) -> list[Violation]:
    f = "reinsurance_treaties.xlsx"
    out: list[Violation] = []
    out += _count(
        "DV-RTY-01",
        f,
        _missing(t, ["treaty_id", "treaty_type", "inception_date", "expiry_date", "currency"]),
        "required field empty",
    )
    out += _count(
        "DV-RTY-02",
        f,
        _unmapped(
            reader,
            "reinsurance_treaties",
            t,
            ["treaty_type", "attachment_basis", "loss_basis", "segment"],
        ),
        "label without a class",
    )
    out += _count(
        "DV-RTY-03", f, t["expiry_date"] <= t["inception_date"], "expiry not after inception"
    )
    out += _count("DV-RTY-04", f, _bad_currency(t["currency"]), "not an ISO 4217 code")
    kind = _class_series(reader, "reinsurance_treaties", "treaty_type", t)
    need = (
        ((kind == "QUOTA_SHARE") & t["cession_share"].is_null())
        | ((kind == "SURPLUS") & (t["retention"].is_null() | t["number_of_lines"].is_null()))
        | (kind.is_in(["EXCESS_OF_LOSS", "STOP_LOSS"]) & t["retention"].is_null())
    )
    out += _count("DV-RTY-05", f, need.fill_null(False), "terms of the type missing")
    shares = pl.Series([False] * t.height)
    for name in ("cession_share", "placed_share", "ceding_commission"):
        shares = shares | ((t[name] < 0) | (t[name] > 1)).fill_null(False)
    out += _count("DV-RTY-06", f, shares, "share outside 0 to 1")
    negative = pl.Series([False] * t.height)
    for name in ("retention", "limit", "aggregate_deductible", "aggregate_limit"):
        negative = negative | (t[name] < 0).fill_null(False)
    out += _count("DV-RTY-07", f, negative, "negative term")
    out += _count(
        "DV-RTY-08",
        f,
        t.height - t.select("treaty_id", "inception_date", "line").n_unique(),
        "treaty, inception date and line repeated",
    )
    market = tables.get("market")
    if market is not None and "cpi" in market:
        series = set(market["cpi"]["series_id"].to_list())
        named = t.filter(pl.col("index_series").is_not_null())
        out += _count(
            "DV-RTY-10",
            f,
            named.filter(~pl.col("index_series").is_in(list(series))).height,
            "index series not in market",
        )
    return out


def _class_series(reader: _Reader, feed: str, field: str, frame: pl.DataFrame) -> pl.Series:
    from actuarycanary.synthetic.check import _class_of

    return _class_of(reader, feed, field, frame[field])


def _transactions(
    reader: _Reader,
    x: pl.DataFrame,
    later: dict[str, pl.DataFrame],
    tables: dict[str, dict[str, pl.DataFrame] | None],
) -> list[Violation]:
    f = "reinsurance_transactions.xlsx"
    out: list[Violation] = []
    out += _count(
        "DV-RTR-01",
        f,
        _missing(x, ["transaction_id", "treaty_id", "booking_date", "amount", "type"]),
        "required field empty",
    )
    out += _count(
        "DV-RTR-02",
        f,
        _unmapped(reader, "reinsurance_transactions", x, ["type", "segment"]),
        "label without a class",
    )
    out += _count("DV-RTR-03", f, _bad_currency(x["currency"]), "currency missing or not ISO 4217")
    out += _count("DV-RTR-04", f, x.height - x["transaction_id"].n_unique(), "identifier repeated")
    kind = _class_series(reader, "reinsurance_transactions", "type", x)
    treaties = later.get("reinsurance_treaties")
    if treaties is not None:
        known = set(treaties["treaty_id"].to_list())
        out += _count(
            "DV-RTR-05",
            f,
            x.filter(~pl.col("treaty_id").is_in(list(known))).height,
            "treaty not in reinsurance_treaties",
        )
        by_claim = x.with_columns(kind.alias("kind")).filter(pl.col("claim_id").is_not_null())
        claims = tables.get("claims")
        if claims is not None:
            occurrence = claims["claims"].select("claim_id", "occurrence_date")
            joined = by_claim.join(occurrence, on="claim_id", how="left").join(
                treaties.select("treaty_id", "inception_date", "expiry_date").unique(),
                on="treaty_id",
                how="left",
            )
            covered = (joined["occurrence_date"] >= joined["inception_date"]) & (
                joined["occurrence_date"] < joined["expiry_date"]
            )
            inside = (
                joined.with_columns(covered.alias("covered"))
                .group_by(["transaction_id"])
                .agg(pl.col("covered").any())
            )
            out += _count(
                "DV-RTR-06",
                f,
                (~inside["covered"]).sum(),
                "claim movement outside every contract period of the treaty",
            )
    claims = tables.get("claims")
    if claims is not None:
        have = x.filter(pl.col("claim_id").is_not_null())
        out += _count(
            "DV-RTR-07",
            f,
            have.filter(~pl.col("claim_id").is_in(claims["claims"]["claim_id"].to_list())).height,
            "claim not in claims",
        )
    valuations = tables.get("claim_valuations")
    if valuations is not None:
        v = valuations["claim_valuations"].select(
            "claim_id",
            "valuation_date",
            "paid_to_date",
            "case_reserve",
            "ceded_paid_to_date",
            "ceded_reserve",
        )
        mv = x.with_columns(kind.alias("kind")).filter(pl.col("claim_id").is_not_null())
        paid = mv.filter(pl.col("kind") == "CEDED_CLAIM_PAID").select(
            "claim_id", "booking_date", "amount"
        )
        reserve = mv.filter(pl.col("kind") == "CEDED_CASE_RESERVE").select(
            "claim_id", "booking_date", "amount"
        )
        v = v.sort(["claim_id", "valuation_date"])
        cp = _cumulative_at(v, paid, "cp")
        cr = _cumulative_at(v, reserve, "cr")
        both = cp.join(cr, on=["claim_id", "valuation_date"])
        both = both.join(v, on=["claim_id", "valuation_date"])
        out += _count(
            "DV-RTR-08",
            f,
            (
                (both["cp"] > both["paid_to_date"] + 0.05)
                | (both["cr"] > both["case_reserve"] + 0.05)
            ).sum(),
            "ceded amount above the gross amount",
        )
        out += _count(
            "DV-RTR-09",
            f,
            (
                ((both["cp"] - both["ceded_paid_to_date"]).abs() > 0.05)
                | ((both["cr"] - both["ceded_reserve"]).abs() > 0.05)
            ).sum(),
            "valuation file and accumulated movements disagree",
        )
    positive = x.with_columns(kind.alias("kind"))
    out += _count(
        "DV-RTR-10",
        f,
        positive.filter(
            pl.col("kind").is_in(
                ["CEDED_CLAIM_PAID", "CEDED_PREMIUM", "RI_COMMISSION", "REINSTATEMENT_PREMIUM"]
            )
            & (pl.col("amount") <= 0)
        ).height,
        "amount not positive",
    )
    premiums = tables.get("premiums")
    policies = tables.get("policies")
    if premiums is not None and policies is not None:
        p = premiums["premiums"].join(
            policies["policies"].select("policy_id", "line"), on="policy_id", how="left"
        )
        ptype = _class_series(reader, "premiums", "type", p)
        ceded = p.with_columns(ptype.alias("kind")).filter(
            pl.col("kind").is_in(["CEDED_PREMIUM", "RI_COMMISSION"])
        )
        if ceded.height:
            feed_side = (
                ceded.with_columns(pl.col("booking_date").dt.month_end().alias("month"))
                .group_by(["kind", "month", "line", "currency"])
                .agg(pl.col("amount").sum().alias("premiums"))
            )
            tx_side = (
                positive.filter(pl.col("kind").is_in(["CEDED_PREMIUM", "RI_COMMISSION"]))
                .with_columns(pl.col("booking_date").dt.month_end().alias("month"))
                .group_by(["kind", "month", "line", "currency"])
                .agg(pl.col("amount").sum().alias("movements"))
            )
            joined = feed_side.join(
                tx_side, on=["kind", "month", "line", "currency"], how="full", coalesce=True
            ).fill_null(0.0)
            out += _count(
                "DV-RTR-11",
                f,
                ((joined["premiums"] - joined["movements"]).abs() > 0.05).sum(),
                "monthly totals differ from the premiums feed",
            )
    return out


def _cumulative_at(valuations: pl.DataFrame, movements: pl.DataFrame, name: str) -> pl.DataFrame:
    """Sum of movements booked on or before each valuation date of the claim."""
    grid = valuations.select("claim_id", "valuation_date")
    steps = (
        movements.group_by(["claim_id", "booking_date"])
        .agg(pl.col("amount").sum())
        .sort(["claim_id", "booking_date"])
    )
    steps = steps.with_columns(pl.col("amount").cum_sum().over("claim_id").alias("cumulative"))
    joined = grid.sort("valuation_date").join_asof(
        steps.sort("booking_date"),
        left_on="valuation_date",
        right_on="booking_date",
        by="claim_id",
        strategy="backward",
    )
    return joined.select(
        "claim_id", "valuation_date", pl.col("cumulative").fill_null(0.0).alias(name)
    )


# --- recoveries ------------------------------------------------------------------------


def _recoveries(
    reader: _Reader, r: pl.DataFrame, tables: dict[str, dict[str, pl.DataFrame] | None]
) -> list[Violation]:
    f = "recoveries.xlsx"
    out: list[Violation] = []
    out += _count(
        "DV-RCV-01",
        f,
        _missing(r, ["transaction_id", "claim_id", "booking_date", "amount", "type"]),
        "required field empty",
    )
    out += _count(
        "DV-RCV-02",
        f,
        _unmapped(reader, "recoveries", r, ["type", "counterparty_type"]),
        "label without a class",
    )
    out += _count("DV-RCV-03", f, _bad_currency(r["currency"]), "currency missing or not ISO 4217")
    out += _count("DV-RCV-04", f, r.height - r["transaction_id"].n_unique(), "identifier repeated")
    valuations = tables.get("claim_valuations")
    if valuations is not None:
        v = valuations["claim_valuations"]
        out += _count(
            "DV-RCV-05",
            f,
            r.filter(~pl.col("claim_id").is_in(v["claim_id"].unique().to_list())).height,
            "claim not in claim_valuations",
        )
        first = v.group_by("claim_id").agg(pl.col("valuation_date").min().alias("first"))
        claims = tables.get("claims")
        report = (
            claims["claims"].select("claim_id", pl.col("report_date").alias("first"))
            if claims is not None
            else first
        )
        early = r.join(report, on="claim_id", how="left").filter(
            pl.col("booking_date") < pl.col("first")
        )
        out += _count("DV-RCV-06", f, early.height, "recovery booked before the claim was reported")
        kind = _class_series(reader, "recoveries", "type", r)
        mv = r.with_columns(kind.alias("kind"))
        for label, column, rule in (
            ("RECOVERY_SUBROGATION", "subrogation_to_date", "DV-RCV-08"),
            ("RECOVERY_SALVAGE", "salvage_to_date", "DV-RCV-08"),
        ):
            steps = mv.filter(pl.col("kind") == label).select("claim_id", "booking_date", "amount")
            cum = _cumulative_at(v.sort(["claim_id", "valuation_date"]), steps, "cum")
            joined = cum.join(
                v.select("claim_id", "valuation_date", column), on=["claim_id", "valuation_date"]
            )
            out += _count(
                rule,
                f,
                ((joined["cum"] - joined[column]).abs() > 0.05).sum(),
                f"{label} differs from {column}",
            )
    out += _count("DV-RCV-09", f, r.filter(pl.col("amount") <= 0).height, "amount not positive")
    return out


# --- ledger ----------------------------------------------------------------------------


def _ledger(reader: _Reader, g: pl.DataFrame) -> list[Violation]:
    f = "ledger.xlsx"
    out: list[Violation] = []
    out += _count(
        "DV-LDG-01",
        f,
        _missing(g, ["entity", "account", "period", "closing_balance"]),
        "required field empty",
    )
    out += _count("DV-LDG-02", f, ~_month_end(g["period"]), "period is not a month end")
    if "currency" in g.columns:
        out += _count("DV-LDG-03", f, _bad_currency(g["currency"]), "currency not ISO 4217")
    out += _count(
        "DV-LDG-04",
        f,
        _unmapped(reader, "ledger", g, ["account_class", "segment"]),
        "label without a class",
    )
    key = ["entity", "account", "period"] + (["currency"] if "currency" in g.columns else [])
    out += _count("DV-LDG-05", f, g.height - g.select(key).n_unique(), "row repeated")
    full = g.filter(
        pl.col("opening_balance").is_not_null()
        & pl.col("debit").is_not_null()
        & pl.col("credit").is_not_null()
    )
    out += _count(
        "DV-LDG-06",
        f,
        (
            (
                full["closing_balance"] - (full["opening_balance"] + full["debit"] - full["credit"])
            ).abs()
            > 0.011
        ).sum(),
        "closing is not opening plus debit minus credit",
    )
    income = {a.code for a in chart() if a.kind == "PL"}
    ordered = g.sort(["entity", "account", "period"]).with_columns(
        pl.col("closing_balance").shift(1).over(["entity", "account"]).alias("previous"),
        pl.col("period").dt.month().alias("month"),
        pl.col("account").is_in(list(income)).alias("income"),
    )
    chained = ordered.filter(
        pl.col("previous").is_not_null() & ~(pl.col("income") & (pl.col("month") == 1))
    )
    out += _count(
        "DV-LDG-07",
        f,
        ((chained["opening_balance"] - chained["previous"]).abs() > 0.011).sum(),
        "opening differs from the closing before",
    )
    if reader.truth is not None and (reader.truth / "ledger_mapping_profile.csv").exists():
        profile = pl.read_csv(reader.truth / "ledger_mapping_profile.csv")
        patterns = [str(p).removesuffix("*") for p in profile["account_pattern"]]
        live = g.group_by(["entity", "account"]).agg(
            pl.col("closing_balance").abs().max().alias("peak")
        )
        live = live.filter(pl.col("peak") > 0)
        unmapped = live.filter(
            ~pl.col("account").map_elements(
                lambda a: any(a.startswith(q) for q in patterns), return_dtype=pl.Boolean
            )
        )
        out += _count(
            "DV-LDG-09", f, unmapped.height, "account with a balance that the profile does not map"
        )
    sums = g.group_by(["entity", "period"]).agg(pl.col("closing_balance").sum().alias("total"))
    out += _count("DV-LDG-08", f, (sums["total"].abs() > 0.05).sum(), "the books do not balance")
    months = g.group_by("entity").agg(
        pl.col("period").min().alias("lo"),
        pl.col("period").max().alias("hi"),
        pl.col("period").n_unique().alias("n"),
    )
    expected = months.with_columns(
        (
            (pl.col("hi").dt.year() - pl.col("lo").dt.year()) * 12
            + pl.col("hi").dt.month()
            - pl.col("lo").dt.month()
            + 1
        ).alias("want")
    )
    out += _count(
        "DV-LDG-10", f, (expected["want"] - expected["n"]).sum(), "entity-months without a row"
    )
    return out


# --- interest rates ---------------------------------------------------------------------


def _rates(reader: _Reader, r: pl.DataFrame) -> list[Violation]:
    f = "interest_rates.xlsx"
    out: list[Violation] = []
    out += _count(
        "DV-IRT-01",
        f,
        _missing(r, ["curve_id", "date", "tenor_months", "rate", "rate_type", "currency"]),
        "required field empty",
    )
    out += _count(
        "DV-IRT-02",
        f,
        _unmapped(reader, "interest_rates", r, ["rate_type", "compounding"]),
        "label without a class",
    )
    tenor = r["tenor_months"]
    out += _count(
        "DV-IRT-03",
        f,
        ((tenor <= 0) | (tenor != tenor.round())).sum(),
        "tenor not a positive whole number",
    )
    out += _count(
        "DV-IRT-04",
        f,
        ((r["rate"] < -0.05) | (r["rate"] > 2.0)).sum(),
        "rate outside -5 to 200 per cent",
    )
    per_curve = r.group_by("curve_id").agg(pl.col("currency").n_unique().alias("n"))
    out += _count(
        "DV-IRT-05",
        f,
        int(_bad_currency(r["currency"]).sum()) + int((per_curve["n"] > 1).sum()),
        "currency not ISO 4217 or not one per curve",
    )
    out += _count(
        "DV-IRT-06",
        f,
        r.height - r.select("curve_id", "date", "tenor_months").n_unique(),
        "rate repeated",
    )
    classes = r.with_columns(
        _class_series(reader, "interest_rates", "rate_type", r).alias("rate_class"),
        _class_series(reader, "interest_rates", "compounding", r)
        .fill_null("ANNUAL")
        .alias("compounding_class"),
    )
    mixed = classes.group_by(["curve_id", "date"]).agg(
        pl.col("rate_class").n_unique().alias("a"),
        pl.col("compounding_class").n_unique().alias("b"),
    )
    out += _count(
        "DV-IRT-07",
        f,
        ((mixed["a"] > 1) | (mixed["b"] > 1)).sum(),
        "more than one rate type or compounding on a curve date",
    )
    spot = r.sort(["curve_id", "date", "tenor_months"])
    forwards = spot.with_columns(
        (
            ((1 + pl.col("rate")) ** (pl.col("tenor_months") / 12))
            / (
                (1 + pl.col("rate").shift(1).over(["curve_id", "date"]))
                ** (pl.col("tenor_months").shift(1).over(["curve_id", "date"]) / 12)
            )
        ).alias("growth"),
        (pl.col("tenor_months") - pl.col("tenor_months").shift(1).over(["curve_id", "date"])).alias(
            "gap"
        ),
    ).filter(pl.col("gap").is_not_null())
    forwards = forwards.with_columns(
        (pl.col("growth") ** (12 / pl.col("gap")) - 1).alias("forward")
    )
    jump = forwards.with_columns(
        pl.col("forward").diff().over(["curve_id", "date"]).abs().alias("jump")
    )
    out += _count(
        "DV-IRT-09",
        f,
        int((forwards["forward"] < -0.05).sum()) + int((jump["jump"] > 0.10).sum()),
        "implied forward rate odd or jumping",
    )
    return out


# --- life and pension --------------------------------------------------------------------


def _life(reader: _Reader, g: pl.DataFrame, events: pl.DataFrame | None) -> list[Violation]:
    f = "life_in_force.xlsx"
    out: list[Violation] = []
    out += _count(
        "DV-LIF-01",
        f,
        _missing(g, ["contract_id", "valuation_date", "entry_date", "age_band", "status"]),
        "required field empty",
    )
    out += _count(
        "DV-LIF-02",
        f,
        _unmapped(
            reader,
            "life_in_force",
            g,
            ["status", "segment", "policy_type", "channel", "premium_frequency", "sex"],
        ),
        "label without a class",
    )
    parts = g["age_band"].str.extract_groups(r"^(\d+)(?:-(\d+))?$")
    low = parts.struct.field("1").cast(pl.Int64, strict=False)
    high = parts.struct.field("2").cast(pl.Int64, strict=False).fill_null(low)
    out += _count(
        "DV-LIF-03",
        f,
        (low.is_null() | (low > high) | (high > 120)).sum(),
        "age_band is not an age or a band",
    )
    out += _count(
        "DV-LIF-04",
        f,
        (g["entry_date"] > g["valuation_date"]).sum(),
        "entry after the valuation date",
    )
    out += _count(
        "DV-LIF-05",
        f,
        g.height - g.select("contract_id", "valuation_date").n_unique(),
        "contract repeated at a date",
    )
    constant = g.group_by("contract_id").agg(
        pl.col("entry_date").n_unique().alias("a"), pl.col("product").n_unique().alias("b")
    )
    out += _count(
        "DV-LIF-06",
        f,
        ((constant["a"] > 1) | (constant["b"] > 1)).sum(),
        "entry date or product changes",
    )
    ordered = (
        g.with_columns(low.alias("age_low"))
        .sort(["contract_id", "valuation_date"])
        .with_columns(
            (pl.col("age_low") - pl.col("age_low").shift(1).over("contract_id")).alias("age_step"),
            (
                (
                    pl.col("valuation_date") - pl.col("valuation_date").shift(1).over("contract_id")
                ).dt.total_days()
                / 365.25
            )
            .round(0)
            .alias("year_step"),
        )
        .filter(pl.col("age_step").is_not_null())
    )
    out += _count(
        "DV-LIF-07",
        f,
        ((ordered["age_step"] - ordered["year_step"]).abs() > 5).sum(),
        "age does not move with time",
    )
    status = _class_series(reader, "life_in_force", "status", g)
    flagged = (
        g.with_columns(status.alias("kind"))
        .sort(["contract_id", "valuation_date"])
        .with_columns(pl.col("kind").shift(1).over("contract_id").alias("before"))
    )
    back = flagged.filter(
        pl.col("kind").is_in(["IN_FORCE", "PAID_UP"])
        & pl.col("before").is_in(
            ["LAPSED", "SURRENDERED", "MATURED", "DEATH_CLAIM", "TRANSFERRED_OUT"]
        )
    )
    if events is not None:
        kinds = _class_series(reader, "life_events", "event_type", events)
        reinstated = events.filter(kinds == "REINSTATEMENT")["contract_id"].to_list()
        back = back.filter(~pl.col("contract_id").is_in(reinstated))
    out += _count(
        "DV-LIF-08", f, back.height, "an exited contract is back in force without a reinstatement"
    )
    out += _count(
        "DV-LIF-09",
        f,
        g.filter(
            (pl.col("sum_assured") < 0)
            | (pl.col("fund_value") < 0)
            | (pl.col("annual_premium") < 0)
        ).height,
        "negative amount",
    )
    last = g.select(pl.col("valuation_date").max()).item()
    exits = flagged.filter(
        pl.col("kind").is_in(["LAPSED", "SURRENDERED", "MATURED", "DEATH_CLAIM", "TRANSFERRED_OUT"])
    )
    gaps = g.group_by("contract_id").agg(
        pl.col("valuation_date").n_unique().alias("n"),
        pl.col("valuation_date").min().alias("first"),
        pl.col("valuation_date").max().alias("last"),
    )
    dates = sorted(set(g["valuation_date"].to_list()))
    count_between = pl.Series(
        [
            sum(1 for d in dates if a <= d <= b)
            for a, b in zip(gaps["first"], gaps["last"], strict=True)
        ]
    )
    out += _count(
        "DV-LIF-10",
        f,
        (count_between - gaps["n"]).sum(),
        "valuation dates without a row between the first and the last",
    )
    del last, exits
    return out


def _events(reader: _Reader, e: pl.DataFrame, g: pl.DataFrame | None) -> list[Violation]:
    f = "life_events.xlsx"
    out: list[Violation] = []
    out += _count(
        "DV-LEV-01",
        f,
        _missing(e, ["event_id", "contract_id", "event_date", "event_type"]),
        "required field empty",
    )
    out += _count(
        "DV-LEV-02", f, _unmapped(reader, "life_events", e, ["event_type"]), "label without a class"
    )
    out += _count("DV-LEV-03", f, e.height - e["event_id"].n_unique(), "identifier repeated")
    kind = _class_series(reader, "life_events", "event_type", e)
    work = e.with_columns(kind.alias("kind"))
    if g is not None:
        entry = g.group_by("contract_id").agg(
            pl.col("entry_date").min(), pl.col("valuation_date").max().alias("cut")
        )
        joined = work.join(entry, on="contract_id", how="left")
        out += _count(
            "DV-LEV-04",
            f,
            joined.filter(pl.col("entry_date").is_null()).height,
            "contract not in life_in_force",
        )
        cut = g["valuation_date"].max()
        out += _count(
            "DV-LEV-05",
            f,
            joined.filter(
                (pl.col("event_date") < pl.col("entry_date")) | (pl.col("event_date") > cut)
            ).height,
            "event outside the life of the contract",
        )
        # DV-LEV-07: the status at the first valuation after a terminal event matches it
        status = g.with_columns(
            _class_series(reader, "life_in_force", "status", g).alias("kind")
        ).sort(["contract_id", "valuation_date"])
        terminal = work.filter(pl.col("kind").is_in(list(TERMINAL))).sort("event_date")
        after = terminal.join_asof(
            status.select("contract_id", "valuation_date", pl.col("kind").alias("status")).sort(
                "valuation_date"
            ),
            left_on="event_date",
            right_on="valuation_date",
            by="contract_id",
            strategy="forward",
        ).filter(pl.col("status").is_not_null())
        wrong = after.filter(
            (pl.col("status") != pl.col("kind").replace_strict(EXIT_STATUS, default=None))
            & (pl.col("status") != "IN_FORCE")
        )
        out += _count("DV-LEV-07", f, wrong.height, "status after the event does not match it")
    ordered = work.sort(["contract_id", "event_date"])
    runs = ordered.with_columns(
        (pl.col("kind") == "REINSTATEMENT").cum_sum().over("contract_id").alias("run"),
        pl.col("kind").is_in(list(TERMINAL)).alias("terminal"),
    )
    twice = (
        runs.filter(pl.col("terminal"))
        .group_by(["contract_id", "run"])
        .agg(pl.len().alias("n"))
        .filter(pl.col("n") > 1)
    )
    out += _count(
        "DV-LEV-06", f, twice.height, "two terminal events without a reinstatement between"
    )
    if "report_date" in e.columns:
        out += _count(
            "DV-LEV-08",
            f,
            (e["report_date"] < e["event_date"]).fill_null(False).sum(),
            "reported before it happened",
        )
    out += _count("DV-LEV-09", f, (e["amount"] < 0).fill_null(False).sum(), "negative amount")
    return out


def _flows(
    reader: _Reader, x: pl.DataFrame, g: pl.DataFrame | None, e: pl.DataFrame | None
) -> list[Violation]:
    f = "fund_flows.xlsx"
    out: list[Violation] = []
    out += _count(
        "DV-FFL-01",
        f,
        _missing(x, ["flow_id", "contract_id", "flow_date", "amount", "flow_type"]),
        "required field empty",
    )
    out += _count(
        "DV-FFL-02", f, _unmapped(reader, "fund_flows", x, ["flow_type"]), "label without a class"
    )
    out += _count("DV-FFL-03", f, _bad_currency(x["currency"]), "currency missing or not ISO 4217")
    out += _count("DV-FFL-04", f, x.height - x["flow_id"].n_unique(), "identifier repeated")
    if g is not None:
        out += _count(
            "DV-FFL-05",
            f,
            x.filter(~pl.col("contract_id").is_in(g["contract_id"].unique().to_list())).height,
            "contract not in life_in_force",
        )
    kind = _class_series(reader, "fund_flows", "flow_type", x)
    work = x.with_columns(kind.alias("kind"))
    switches = work.filter(pl.col("kind") == "FUND_SWITCH")
    sums = switches.group_by(["contract_id", "flow_date"]).agg(pl.col("amount").sum().alias("net"))
    out += _count(
        "DV-FFL-06",
        f,
        (sums["net"].abs() > 0.01).sum() + switches.filter(pl.col("fund_code").is_null()).height,
        "switch rows do not net to zero or lack a fund",
    )
    out += _count(
        "DV-FFL-07",
        f,
        work.filter((pl.col("kind") != "FUND_SWITCH") & (pl.col("amount") <= 0)).height,
        "amount not positive",
    )
    if e is not None:
        ev = e.with_columns(
            _class_series(reader, "life_events", "event_type", e).alias("kind")
        ).sort(["contract_id", "event_date"])
        last_terminal = (
            ev.filter(pl.col("kind").is_in(list(TERMINAL)))
            .group_by("contract_id")
            .agg(pl.col("event_date").max().alias("terminal"))
        )
        restart = (
            ev.filter(pl.col("kind") == "REINSTATEMENT")
            .group_by("contract_id")
            .agg(pl.col("event_date").max().alias("restart"))
        )
        late = (
            work.filter(pl.col("kind") == "CONTRIBUTION")
            .join(last_terminal, on="contract_id", how="inner")
            .join(restart, on="contract_id", how="left")
            .filter(
                (pl.col("flow_date") > pl.col("terminal"))
                & (pl.col("restart").is_null() | (pl.col("restart") < pl.col("terminal")))
            )
        )
        out += _count("DV-FFL-08", f, late.height, "contribution after a terminal event")
    return out
