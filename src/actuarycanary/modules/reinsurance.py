"""M08 Reinsurance: what is ceded and what is net, treaty by treaty, the reconciliation with
the ceded amounts the data report, and what another programme would cede (MT21, CV09)."""

from dataclasses import dataclass
from datetime import date

import polars as pl
from pydantic import BaseModel, ConfigDict, field_validator

from actuarycanary.convert.allocation import AGGREGATE, FALLBACKS, Allocation, allocate
from actuarycanary.io.excel import SOURCE_COLUMNS
from actuarycanary.measures.model import REF, MeasureInputs
from actuarycanary.methods.reinsurance.application import Application
from actuarycanary.methods.reinsurance.index import INDEX_CLAUSES, PAYMENT_BY_PAYMENT
from actuarycanary.methods.reinsurance.terms import Section
from actuarycanary.modules.reinsurance_inputs import ReinsuranceInputs, apply, assemble

LOSS_VIEWS = ("incurred", "ultimate")
PROGRAMMES = ("loaded", "alternative", "both")


class ReinsuranceSettings(BaseModel):
    """Settings of M08 and MT21 (records 0401, 0403 and 0408); part of the run id."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # how an index clause works: payment by payment (the owner's choice, record 0401) or
    # fixed at the occurrence date (the generator's clause)
    index_clause: str = PAYMENT_BY_PAYMENT
    # CV09: what happens to a treaty-level amount that cannot be allocated to claims or policies
    allocation_fallback: str = AGGREGATE
    # MT21: the loaded treaties, an alternative from the assumptions register, or both
    programme: str = "loaded"
    loss_view: str = "ultimate"
    # MT21 `simulate` is not built (record 0408): only false is accepted
    simulate: bool = False
    inuring_order: str = "CV09"

    @field_validator("index_clause")
    @classmethod
    def _known_clause(cls, value: str) -> str:
        if value not in INDEX_CLAUSES:
            raise ValueError(
                f"index clause {value!r} is unknown; known: {', '.join(INDEX_CLAUSES)}"
            )
        return value

    @field_validator("allocation_fallback")
    @classmethod
    def _known_fallback(cls, value: str) -> str:
        if value not in FALLBACKS:
            raise ValueError(
                f"allocation fallback {value!r} is unknown; known: {', '.join(FALLBACKS)}"
            )
        return value

    @field_validator("programme")
    @classmethod
    def _known_programme(cls, value: str) -> str:
        if value not in PROGRAMMES:
            raise ValueError(f"programme {value!r} is unknown; known: {', '.join(PROGRAMMES)}")
        return value

    @field_validator("loss_view")
    @classmethod
    def _known_view(cls, value: str) -> str:
        if value not in LOSS_VIEWS:
            raise ValueError(f"loss view {value!r} is unknown; known: incurred and ultimate")
        return value

    @field_validator("simulate")
    @classmethod
    def _not_built(cls, value: bool) -> bool:
        if value:
            raise ValueError("simulate is not built (MT21, record 0408): only false is accepted")
        return value

    @field_validator("inuring_order")
    @classmethod
    def _cv09_only(cls, value: str) -> str:
        if value != "CV09":
            raise ValueError("inuring order: only CV09 is built (record 0604)")
        return value


# ------------------------------------------------------------------ the run of M08

SETTINGS_KEY = "reinsurance_settings"
RUN_KEY = "reinsurance_run"
TREATIES = "reinsurance_treaties"
MOVEMENTS = "reinsurance_transactions"
CLAIM_TYPES = ("CEDED_CLAIM_PAID", "CEDED_CASE_RESERVE")
# the reconciliation (record 0405): a treaty year differs when computed and reported ceded
# incurred are further apart than 1 per cent of the larger, and at least 1.00
RELATIVE_TOLERANCE = 0.01
ABSOLUTE_TOLERANCE = 1.0
SIZE_BANDS = (0.0, 1e4, 1e5, 1e6, 1e7)  # reporting currency, gross incurred at the cut-off


def _band_label(lower: float, upper: float | None) -> str:
    def text(x: float) -> str:
        return f"{x / 1e6:g}m" if x >= 1e6 else f"{x / 1e3:g}k" if x >= 1e3 else f"{x:g}"

    return f"{text(lower)} and above" if upper is None else f"{text(lower)} to {text(upper)}"


@dataclass(frozen=True)
class ReinsuranceRun:
    """The treaty application of a run with its allocation, tables and reconciliation."""

    settings: ReinsuranceSettings
    inputs: ReinsuranceInputs
    application: Application | None
    allocation: Allocation | None
    cut_off: date
    reporting_currency: str
    treaty_refs: pl.DataFrame  # treaty_id, inception_date, refs (the `_ref` of the treaty rows)

    # helpers ----------------------------------------------------------------------------------

    def _rate(self, frame: pl.DataFrame, currency: str, target: str) -> pl.Series:
        """Constant rate of each row's currency into `target` at the cut-off (CV01)."""
        fx = self.inputs.options.fx
        codes = frame[currency].to_list() if currency in frame.columns else [None] * frame.height
        cache: dict[object, float] = {}
        out = []
        for code in codes:
            if code is None or code == target:
                out.append(1.0)
                continue
            if code not in cache:
                rate = None if fx is None else fx(str(code), target, self.cut_off)
                cache[code] = float("nan") if rate is None else rate
            out.append(cache[code])
        return pl.Series("rate", out, dtype=pl.Float64)

    def _claim_currency(self) -> pl.DataFrame:
        book = self.inputs.book
        if book is None or "currency" not in book.claims.columns:
            return pl.DataFrame(schema={"claim_id": pl.String, "currency": pl.String})
        return book.claims.select("claim_id", "currency")

    def _gross_at_cut_off(self) -> pl.DataFrame:
        book = self.inputs.book
        assert book is not None
        return (
            book.valuations.filter(pl.col("valuation_date") <= self.cut_off)
            .sort("valuation_date")
            .group_by("claim_id")
            .last()
            .select("claim_id", "paid", "incurred")
        )

    def _section_currency(self) -> dict[tuple[str, date], str]:
        return {s.key: s.currency for s in self.inputs.sections}

    def _in_treaty_currency(self, frame: pl.DataFrame, columns: list[str]) -> pl.DataFrame:
        """Columns of rows in claim currency (`currency`) converted into the section currency."""
        currencies = self._section_currency()
        target = [
            currencies.get((t, d), self.reporting_currency)
            for t, d in zip(
                frame["treaty_id"].to_list(), frame["inception_date"].to_list(), strict=True
            )
        ]
        out = frame.with_columns(pl.Series("target", target, dtype=pl.String))
        rates = []
        fx = self.inputs.options.fx
        for code, aim in zip(out["currency"].to_list(), target, strict=True):
            if code is None or code == aim:
                rates.append(1.0)
            else:
                rate = None if fx is None else fx(str(code), aim, self.cut_off)
                rates.append(float("nan") if rate is None else rate)
        rate = pl.Series("rate", rates, dtype=pl.Float64)
        return out.with_columns([pl.col(c) * rate for c in columns]).drop("target")

    def _clause(self, section: Section) -> str:
        """The index clause in use beside an indexed treaty (record 0401)."""
        if not section.index_series or section.treaty_type == "STOP_LOSS":
            return ""
        if section.series_missing(self.inputs.options.price_index):
            return "none: index series missing"
        if section.treaty_type == "SURPLUS":
            return "line at the policy start"
        return "" if section.is_proportional else self.settings.index_clause

    # tables ----------------------------------------------------------------------------------

    def computed_by_section(self) -> pl.DataFrame:
        """Gross in scope and computed ceded at the cut-off per section, treaty currency."""
        schema = {
            "treaty_id": pl.String,
            "inception_date": pl.Date,
            "claims_in_scope": pl.Int64,
            "gross_incurred": pl.Float64,
            "computed_ceded_paid": pl.Float64,
            "computed_ceded_incurred": pl.Float64,
        }
        app = self.application
        if app is None:
            return pl.DataFrame(schema=schema)
        currency = self._claim_currency()
        gross = self._in_treaty_currency(
            app.scope.join(self._gross_at_cut_off(), on="claim_id", how="left").join(
                currency, on="claim_id", how="left"
            ),
            ["incurred"],
        )
        gross = gross.group_by(["treaty_id", "inception_date"]).agg(
            pl.len().cast(pl.Int64).alias("claims_in_scope"),
            pl.col("incurred").sum().alias("gross_incurred"),
        )
        ceded = (
            self._in_treaty_currency(
                app.ceded_at(self.cut_off).join(currency, on="claim_id", how="left"),
                ["ceded_paid", "ceded_incurred"],
            )
            .group_by(["treaty_id", "inception_date"])
            .agg(
                pl.col("ceded_paid").sum().alias("computed_ceded_paid"),
                pl.col("ceded_incurred").sum().alias("computed_ceded_incurred"),
            )
        )
        return (
            gross.join(ceded, on=["treaty_id", "inception_date"], how="left")
            .with_columns(
                pl.col("computed_ceded_paid").fill_null(0.0),
                pl.col("computed_ceded_incurred").fill_null(0.0),
            )
            .cast(schema)  # type: ignore[arg-type]
        )

    def _claim_section(self) -> pl.DataFrame:
        app = self.application
        if app is None:
            return pl.DataFrame(
                schema={"treaty_id": pl.String, "inception_date": pl.Date, "claim_id": pl.String}
            )
        return app.scope

    def reported_claims(self) -> pl.DataFrame:
        """Reported ceded claim movements up to the cut-off per section and claim: given, or
        allocated per CV09 (claims; cells by origin year), in the movement's currency."""
        schema = {
            "treaty_id": pl.String,
            "inception_date": pl.Date,
            "claim_id": pl.String,
            "currency": pl.String,
            "reported_ceded_paid": pl.Float64,
            "reported_ceded_incurred": pl.Float64,
        }
        if self.allocation is None:
            return pl.DataFrame(schema=schema)
        rows = self.allocation.rows.filter(
            pl.col("type").is_in(CLAIM_TYPES) & (pl.col("booking_date") <= self.cut_off)
        )
        by_claim = rows.filter(pl.col("claim_id").is_not_null()).join(
            self._claim_section(), on=["treaty_id", "claim_id"], how="inner"
        )
        starts = {s.key: s.inception for s in self.inputs.sections}
        cells = rows.filter(pl.col("claim_id").is_null() & pl.col("origin_year").is_not_null())
        if cells.height:
            years = pl.DataFrame(
                {
                    "treaty_id": [k[0] for k in starts],
                    "inception_date": list(starts.values()),
                    "origin_year": [d.year for d in starts.values()],
                },
                schema={"treaty_id": pl.String, "inception_date": pl.Date, "origin_year": pl.Int64},
            )
            cells = cells.join(years, on=["treaty_id", "origin_year"], how="inner")
        parts = (
            pl.concat(
                [by_claim.select(sorted(by_claim.columns)), cells.select(sorted(by_claim.columns))]
            )
            if cells.height
            else by_claim
        )
        return (
            parts.group_by(["treaty_id", "inception_date", "claim_id", "currency"])
            .agg(
                pl.col("amount")
                .filter(pl.col("type") == "CEDED_CLAIM_PAID")
                .sum()
                .alias("reported_ceded_paid"),
                pl.col("amount").sum().alias("reported_ceded_incurred"),
            )
            .cast(schema)  # type: ignore[arg-type]
        )

    def reported_by_section(self) -> pl.DataFrame:
        reported = self.reported_claims()
        converted = self._in_treaty_currency(
            reported, ["reported_ceded_paid", "reported_ceded_incurred"]
        )
        claims = converted.group_by(["treaty_id", "inception_date"]).agg(
            pl.col("reported_ceded_paid").sum(), pl.col("reported_ceded_incurred").sum()
        )
        movements = self.inputs.movements
        rows = []
        for s in self.inputs.sections:
            if movements is None:
                break
            mine = movements.filter(
                (pl.col("treaty_id") == s.treaty_id)
                & (pl.col("booking_date") >= s.inception)
                & (pl.col("booking_date") < s.expiry)
                & (pl.col("booking_date") <= self.cut_off)
            )
            if "currency" in mine.columns:
                mine = mine.with_columns(
                    pl.Series("treaty_id", [s.treaty_id] * mine.height),
                    pl.lit(s.inception).alias("inception_date"),
                )
                mine = self._in_treaty_currency(mine, ["amount"])
            row = {"treaty_id": s.treaty_id, "inception_date": s.inception}
            for kind, name in (
                ("CEDED_PREMIUM", "reported_ceded_premium"),
                ("RI_COMMISSION", "reported_commission"),
                ("REINSTATEMENT_PREMIUM", "reported_reinstatement_premium"),
            ):
                row[name] = float(mine.filter(pl.col("type") == kind)["amount"].sum())
            rows.append(row)
        premium = pl.DataFrame(
            rows,
            schema={
                "treaty_id": pl.String,
                "inception_date": pl.Date,
                "reported_ceded_premium": pl.Float64,
                "reported_commission": pl.Float64,
                "reported_reinstatement_premium": pl.Float64,
            },
        )
        return premium.join(claims, on=["treaty_id", "inception_date"], how="full", coalesce=True)

    def treaty_table(self) -> pl.DataFrame:
        """ceded_by_treaty.csv: one row per treaty and treaty year (record 0406)."""
        sections = self.inputs.sections
        if not sections:
            return pl.DataFrame()
        results = {
            r.section.key: r for r in (self.application.sections if self.application else [])
        }
        base = pl.DataFrame(
            [
                {
                    "treaty_id": s.treaty_id,
                    "treaty_year": s.inception.year,
                    "inception_date": s.inception,
                    "expiry_date": s.expiry,
                    "treaty_type": s.treaty_type,
                    "loss_basis": s.loss_basis,
                    "lines": "" if s.lines is None else ", ".join(sorted(s.lines)),
                    "currency": s.currency,
                    "cession_share": s.cession_share,
                    "retention": s.retention,
                    "limit": s.limit,
                    "placed_share": s.placed_share,
                    "index_clause": self._clause(s),
                }
                for s in sections
            ],
            infer_schema_length=None,
        )
        premium = (
            self.inputs.premium.by_section.select(
                "treaty_id",
                "inception_date",
                "gross_written",
                pl.col("ceded_premium").alias("computed_ceded_premium"),
                pl.col("commission").alias("computed_commission"),
            )
            if self.inputs.premium is not None
            else None
        )
        layers = (
            self.application.layer_frame().select(
                "treaty_id",
                "inception_date",
                "units_hit",
                "units_exhausted",
                "aggregate_exhausted",
                "reinstatements_used",
                pl.col("reinstatement_premium").alias("computed_reinstatement_premium"),
                "notes",
            )
            if self.application is not None and results
            else None
        )
        out = base.join(self.computed_by_section(), on=["treaty_id", "inception_date"], how="left")
        if self.application is not None:  # a section without claims in scope cedes nothing
            out = out.with_columns(
                pl.col(c).fill_null(0)
                for c in (
                    "claims_in_scope",
                    "gross_incurred",
                    "computed_ceded_paid",
                    "computed_ceded_incurred",
                )
            )
        out = out.join(self.reported_by_section(), on=["treaty_id", "inception_date"], how="left")
        for extra in (premium, layers):
            if extra is not None:
                out = out.join(extra, on=["treaty_id", "inception_date"], how="left")
        return out.sort(["treaty_id", "treaty_year"])

    def reconciliation(self) -> pl.DataFrame:
        """Computed against reported ceded incurred per treaty year, and the claims of a treaty
        year that differs (record 0405); one row per difference, both sides shown."""
        schema = {
            "level": pl.String,
            "treaty_id": pl.String,
            "treaty_year": pl.Int64,
            "claim_id": pl.String,
            "computed_ceded_incurred": pl.Float64,
            "reported_ceded_incurred": pl.Float64,
            "difference": pl.Float64,
            "differs": pl.Boolean,
        }
        table = self.treaty_table()
        if table.height == 0 or "reported_ceded_incurred" not in table.columns:
            return pl.DataFrame(schema=schema)
        years = (
            table.filter(
                pl.col("reported_ceded_incurred").is_not_null()
                | (pl.col("computed_ceded_incurred").fill_null(0) != 0)
            )
            .select(
                pl.lit("treaty year").alias("level"),
                "treaty_id",
                pl.col("treaty_year").cast(pl.Int64),
                pl.lit(None, dtype=pl.String).alias("claim_id"),
                pl.col("computed_ceded_incurred").fill_null(0.0),
                pl.col("reported_ceded_incurred").fill_null(0.0),
            )
            .with_columns(
                (pl.col("computed_ceded_incurred") - pl.col("reported_ceded_incurred")).alias(
                    "difference"
                )
            )
            .with_columns(_differs().alias("differs"))
        )
        differing = years.filter(pl.col("differs")).select("treaty_id", "treaty_year")
        if differing.height == 0 or self.application is None:
            return years.cast(schema).sort(["treaty_id", "treaty_year"])  # type: ignore[arg-type]
        computed = self.application.ceded_at(self.cut_off).select(
            "treaty_id",
            "inception_date",
            "claim_id",
            pl.col("ceded_incurred").alias("computed_ceded_incurred"),
        )
        reported = (
            self.reported_claims()
            .filter(pl.col("claim_id").is_not_null())
            .select("treaty_id", "inception_date", "claim_id", "reported_ceded_incurred")
        )
        claims = (
            computed.join(
                reported, on=["treaty_id", "inception_date", "claim_id"], how="full", coalesce=True
            )
            .with_columns(pl.col("inception_date").dt.year().cast(pl.Int64).alias("treaty_year"))
            .join(differing, on=["treaty_id", "treaty_year"], how="semi")
            .select(
                pl.lit("claim").alias("level"),
                "treaty_id",
                "treaty_year",
                "claim_id",
                pl.col("computed_ceded_incurred").fill_null(0.0),
                pl.col("reported_ceded_incurred").fill_null(0.0),
            )
            .with_columns(
                (pl.col("computed_ceded_incurred") - pl.col("reported_ceded_incurred")).alias(
                    "difference"
                )
            )
            .with_columns(_differs().alias("differs"))
            .filter(pl.col("differs"))
        )
        return pl.concat([years.cast(schema), claims.cast(schema)]).sort(  # type: ignore[arg-type]
            ["treaty_id", "treaty_year", "level", "claim_id"], nulls_last=False
        )

    def allocation_table(self) -> pl.DataFrame:
        """ceded_allocation.csv: the movements as given or allocated, with the method used, by
        treaty, type, target, line and origin year (claims) or policy start year (policies)."""
        if self.allocation is None:
            return pl.DataFrame()
        rows = self.allocation.rows
        book = self.inputs.book
        if book is not None and "occurrence_date" in book.claims.columns:
            claim_cells = book.claims.select(
                "claim_id",
                pl.col("line").alias("claim_line")
                if "line" in book.claims.columns
                else pl.lit(None, dtype=pl.String).alias("claim_line"),
                pl.col("occurrence_date").dt.year().cast(pl.Int64).alias("claim_year"),
            )
            rows = rows.join(claim_cells, on="claim_id", how="left")
        else:
            rows = rows.with_columns(
                pl.lit(None, dtype=pl.String).alias("claim_line"),
                pl.lit(None, dtype=pl.Int64).alias("claim_year"),
            )
        policies = book.policies if book is not None else None
        if policies is not None and {"policy_id", "start_date"} <= set(policies.columns):
            policy_cells = policies.select(
                "policy_id",
                pl.col("line").alias("policy_line")
                if "line" in policies.columns
                else pl.lit(None, dtype=pl.String).alias("policy_line"),
                pl.col("start_date").dt.year().cast(pl.Int64).alias("policy_year"),
            ).unique("policy_id")
            rows = rows.join(policy_cells, on="policy_id", how="left")
        else:
            rows = rows.with_columns(
                pl.lit(None, dtype=pl.String).alias("policy_line"),
                pl.lit(None, dtype=pl.Int64).alias("policy_year"),
            )
        rows = rows.with_columns(
            pl.coalesce("line", "claim_line", "policy_line").alias("line"),
            pl.coalesce("origin_year", "claim_year", "policy_year").alias("year"),
        )
        return (
            rows.group_by(["treaty_id", "type", "method", "target", "line", "year", "currency"])
            .agg(pl.len().cast(pl.Int64).alias("parts"), pl.col("amount").sum().round(2))
            .sort(
                ["treaty_id", "type", "method", "target", "line", "year", "currency"],
                nulls_last=True,
            )
        )

    def size_bands(self) -> pl.DataFrame:
        """Computed ceded share of gross incurred at the cut-off by claim size band and treaty
        (MT21 diagnostic); bands in the reporting currency at the constant cut-off rate."""
        if self.application is None or self.inputs.book is None:
            return pl.DataFrame()
        gross = self._gross_at_cut_off().join(self._claim_currency(), on="claim_id", how="left")
        rate = self._rate(gross, "currency", self.reporting_currency)
        gross = gross.with_columns((pl.col("incurred") * rate).alias("gross"), rate.alias("rate"))
        edges = list(SIZE_BANDS)
        labels = [_band_label(lo, hi) for lo, hi in zip(edges, [*edges[1:], None], strict=True)]
        band = pl.lit(labels[0])
        for lo, label in zip(edges[1:], labels[1:], strict=True):
            band = pl.when(pl.col("gross") >= lo).then(pl.lit(label)).otherwise(band)
        gross = gross.with_columns(band.alias("size_band"))
        ceded = self.application.ceded_at(self.cut_off).join(
            gross.select("claim_id", "rate", "size_band"), on="claim_id"
        )
        by_treaty = ceded.group_by(["size_band", "treaty_id"]).agg(
            (pl.col("ceded_incurred") * pl.col("rate")).sum().alias("ceded_incurred")
        )
        totals = gross.group_by("size_band").agg(
            pl.len().cast(pl.Int64).alias("claims"), pl.col("gross").sum().alias("gross_incurred")
        )
        order = {label: i for i, label in enumerate(labels)}
        return (
            by_treaty.join(totals, on="size_band", how="left")
            .with_columns(
                pl.when(pl.col("gross_incurred") > 0)
                .then(pl.col("ceded_incurred") / pl.col("gross_incurred"))
                .alias("ceded_share"),
                pl.col("size_band").replace_strict(order, return_dtype=pl.Int64).alias("_order"),
            )
            .sort(["_order", "treaty_id"])
            .drop("_order")
            .select(
                "size_band",
                "claims",
                "gross_incurred",
                "treaty_id",
                "ceded_incurred",
                "ceded_share",
            )
        )


def _differs() -> pl.Expr:
    larger = pl.max_horizontal(
        pl.col("computed_ceded_incurred").abs(), pl.col("reported_ceded_incurred").abs()
    )
    return pl.col("difference").abs() > pl.max_horizontal(
        pl.lit(ABSOLUTE_TOLERANCE), larger * RELATIVE_TOLERANCE
    )


def _frame(feed: pl.DataFrame | None) -> pl.DataFrame | None:
    if feed is None:
        return None
    drop = [c for c in (REF, *SOURCE_COLUMNS) if c in feed.columns]
    return feed.drop(drop)


def reinsurance_run(inputs: MeasureInputs) -> ReinsuranceRun | None:
    """The treaty application of the run, built once and kept in the inputs' cache; None
    without treaties."""
    if RUN_KEY in inputs.cache:
        return inputs.cache[RUN_KEY]
    treaties = inputs.feeds.get(TREATIES)
    if treaties is None or treaties.height == 0:
        inputs.cache[RUN_KEY] = None
        return None
    settings: ReinsuranceSettings = inputs.cache.get(SETTINGS_KEY, ReinsuranceSettings())
    frames: dict[str, pl.DataFrame] = {}
    for concept in (
        "claim_valuations",
        "claims",
        "policies",
        "premiums",
        "market",
        TREATIES,
        MOVEMENTS,
    ):
        frame = _frame(inputs.feeds.get(concept))
        if frame is None:
            continue
        if concept == "claim_valuations":
            frame = frame.filter(pl.col("valuation_date") <= inputs.cut_off)
        if concept == MOVEMENTS and "booking_date" in frame.columns:
            frame = frame.filter(pl.col("booking_date") <= inputs.cut_off)
        frames[concept] = frame
    ri_inputs = assemble(frames, settings.index_clause)
    application = apply(ri_inputs)
    allocation = (
        allocate(
            ri_inputs.movements,
            ri_inputs.sections,
            ri_inputs.book,
            application,
            ri_inputs.written,
            settings.allocation_fallback,
        )
        if ri_inputs.movements is not None
        else None
    )
    refs = (
        treaties.select("treaty_id", "inception_date", REF)
        .group_by(["treaty_id", "inception_date"])
        .agg(pl.col(REF).sort().alias("refs"))
    )
    run = ReinsuranceRun(
        settings,
        ri_inputs,
        application,
        allocation,
        inputs.cut_off,
        inputs.reporting_currency,
        refs,
    )
    inputs.cache[RUN_KEY] = run
    return run
