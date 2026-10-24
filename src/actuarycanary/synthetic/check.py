"""Checks a folder of spreadsheets against spec/data/ and lists every violation.

Layout (header row, renamed columns, text dates, label aliases) is undone with the files in
``truth/`` when they exist, so messy files can be judged on their content. Only rules that
can be decided from the six files alone are checked; each violation names its rule ID from
the specification (``DV-CLV-07`` and so on) and counts the rows that break it.
"""

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl
import yaml

from actuarycanary.spec.loader import find_spec_root
from actuarycanary.synthetic.messy import Dictionaries
from actuarycanary.synthetic.writer import sha256

TEXT_DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y")
PAIR = re.compile(r"^[A-Z]{3}/[A-Z]{3}$")
CURRENCY = re.compile(r"^[A-Z]{3}$")
FEED_FILES = ("claim_valuations", "claims", "policies", "premiums", "expenses", "market")
_FOLD = str.maketrans(
    {
        "İ": "I",
        "ı": "I",
        "Ö": "O",
        "ö": "O",
        "Ü": "U",
        "ü": "U",
        "Ş": "S",
        "ş": "S",
        "Ç": "C",
        "ç": "C",
        "Ğ": "G",
        "ğ": "G",
    }
)


@dataclass(frozen=True)
class Violation:
    rule: str
    file: str
    count: int
    detail: str


def normalise_label(text: str) -> str:
    """Turkish letters folded, upper case, punctuation and spaces removed."""
    return re.sub(r"[^A-Z0-9]", "", text.translate(_FOLD).upper())


class _Reader:
    def __init__(self, folder: Path, truth: Path | None) -> None:
        self.folder = folder
        self.truth = truth if truth is not None and truth.is_dir() else None
        self.dictionaries = Dictionaries()
        self.spec = {
            p.stem: yaml.safe_load(p.read_text(encoding="utf-8"))
            for p in (find_spec_root() / "data").glob("*.yaml")
        }
        if self.truth is not None:
            # the logs of the feeds added after version 1.0 are in files of their own
            self.layout = _logs(self.truth, "layout")
            self.columns = _logs(self.truth, "column_map")

    def read(self, feed: str) -> dict[str, pl.DataFrame] | None:
        paths = [self.folder / f"{feed}.xlsx"]
        if not paths[0].exists():
            paths = sorted(self.folder.glob(f"{feed}_part*.xlsx"))  # a feed split over workbooks
        if not paths:
            return None
        keys = ["fx", "cpi"] if feed == "market" else [feed]
        parts: dict[str, list[pl.DataFrame]] = {}
        for path in paths:
            header_rows = {}
            if self.truth is not None:
                rows = self.layout.filter(pl.col("file") == path.name)
                header_rows = dict(zip(rows["sheet"], rows["header_row"], strict=True))
            sheets = (
                list(header_rows) if header_rows else ["fx", "cpi"] if feed == "market" else [None]
            )
            for position, sheet in enumerate(sheets):
                frame = read_sheet(path, sheet, header_rows.get(sheet, 1))
                parts.setdefault(keys[position], []).append(
                    self._canonical(feed, str(sheet), frame)
                )
        return {key: pl.concat(frames) for key, frames in parts.items()}

    def _canonical(self, feed: str, sheet: str, frame: pl.DataFrame) -> pl.DataFrame:
        if self.truth is not None:
            mapping = self.columns.filter(
                (pl.col("file") == feed) & (pl.col("sheet") == sheet) & (pl.col("field") != "")
            )
            by_header = dict(zip(mapping["header"], mapping["field"], strict=True))
            renamed = {by_header[h]: h for h in frame.columns if h in by_header}
            frame = frame.select(
                [
                    pl.col(renamed[f["name"]]).alias(f["name"])
                    for f in self.spec[feed]["fields"]
                    if f["name"] in renamed
                ]
            )
        wanted = {f["name"]: f for f in self.spec[feed]["fields"]}
        casts = []
        for name in frame.columns:
            kind = wanted.get(name, {}).get("type")
            if kind == "date" and frame[name].dtype != pl.Date:
                casts.append(_parse_dates(name, frame[name]))
        return frame.with_columns(casts) if casts else frame


def _logs(truth: Path, name: str) -> pl.DataFrame:
    frame = pl.read_csv(truth / f"{name}.csv")
    later = truth / f"{name}_phase2.csv"
    return pl.concat([frame, pl.read_csv(later)]) if later.exists() else frame


def read_sheet(path: Path, sheet: str | None, header_row: int) -> pl.DataFrame:
    """One worksheet as read by calamine, cached as parquet keyed by the file's SHA-256."""
    cache = find_spec_root().parent / ".cache" / "synthetic"
    key = f"{sha256(path)[:24]}-{sheet or 'first'}-{header_row}-all.parquet"
    if (cache / key).exists():
        return pl.read_parquet(cache / key)
    options = {"header_row": header_row - 1}
    if sheet:
        frame = pl.read_excel(
            path,
            sheet_name=sheet,
            engine="calamine",
            read_options=options,
            infer_schema_length=None,  # as the reader of the product: all cells decide the type
        )
    else:
        frame = pl.read_excel(
            path, engine="calamine", read_options=options, infer_schema_length=None
        )
    cache.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(cache / key)
    return frame


def _parse_dates(name: str, column: pl.Series) -> pl.Series:
    if column.dtype != pl.String:
        return column.cast(pl.Date, strict=False).alias(name)
    parsed = [column.str.to_datetime(fmt, strict=False).dt.date() for fmt in TEXT_DATE_FORMATS]
    return pl.select(pl.coalesce(parsed)).to_series().alias(name)


def _extra_copies(frame: pl.DataFrame) -> int:
    """Rows beyond the first of each repeated row."""
    return frame.height - frame.n_unique()


def _count(rule: str, file: str, mask: pl.Series | int, detail: str) -> list[Violation]:
    n = int(mask.sum()) if isinstance(mask, pl.Series) else int(mask)
    return [Violation(rule, file, n, detail)] if n else []


def _class_ok(
    reader: _Reader, feed: str, field: str, values: pl.Series, classes: list[str]
) -> pl.Series:
    """True where a non-empty label is a class name or a dictionary alias of one."""
    known = {normalise_label(c) for c in classes}
    for aliases in reader.dictionaries.values.get((feed, field), {}).values():
        known |= {normalise_label(a) for a in aliases}
    return values.map_elements(
        lambda v: v is not None and normalise_label(str(v)) in known,
        return_dtype=pl.Boolean,
        skip_nulls=False,
    )


def _lookup_classes(
    dictionaries: Dictionaries, feed: str, field: str, values: pl.Series
) -> pl.Series:
    lookup: dict[str, str] = {}
    for cls, aliases in dictionaries.values.get((feed, field), {}).items():
        lookup[normalise_label(cls)] = cls
        for alias in aliases:
            lookup[normalise_label(alias)] = cls
    return values.map_elements(
        lambda v: lookup.get(normalise_label(str(v))) if v is not None else None,
        return_dtype=pl.String,
        skip_nulls=False,
    )


def _class_of(reader: _Reader, feed: str, field: str, values: pl.Series) -> pl.Series:
    return _lookup_classes(reader.dictionaries, feed, field, values)


def read_feed(folder: Path, feed: str, truth: Path | None = None) -> dict[str, pl.DataFrame] | None:
    """One feed in canonical shape: header row found, columns renamed to spec fields, personal
    columns dropped, text dates parsed. None when the file does not exist."""
    return _Reader(folder, truth if truth is not None else folder / "truth").read(feed)


def class_of(feed: str, field: str, values: pl.Series) -> pl.Series:
    """The class (OPEN, CLOSED, ...) of each label through the value dictionaries."""
    return _lookup_classes(Dictionaries(), feed, field, values)


def check_folder(
    folder: Path, truth: Path | None = None, later_feeds: bool = False
) -> list[Violation]:
    """Every violation found in the spreadsheets under `folder` (truth defaults to folder/truth).

    The rules of the feeds added after version 1.0 are checked too when `later_feeds` is true."""
    reader = _Reader(folder, truth if truth is not None else folder / "truth")
    tables = {feed: reader.read(feed) for feed in FEED_FILES}
    found: list[Violation] = []
    if tables["claim_valuations"] is None:
        return [Violation("FILE", "claim_valuations.xlsx", 1, "the required file is missing")]
    for feed, sheets in tables.items():
        if sheets is None:
            continue
        for frame in sheets.values():
            found += _schema(reader, feed, frame)
    v = tables["claim_valuations"]["claim_valuations"]
    claims = tables["claims"]["claims"] if tables["claims"] else None
    policies = tables["policies"]["policies"] if tables["policies"] else None
    found += _valuations(reader, v, claims)
    if claims is not None:
        found += _claims(reader, claims, v, policies)
    if policies is not None:
        found += _policies(reader, policies)
    if tables["premiums"] is not None:
        found += _premiums(reader, tables["premiums"]["premiums"], policies)
    if tables["expenses"] is not None:
        found += _expenses(reader, tables["expenses"]["expenses"])
    if tables["market"] is not None:
        found += _market(reader, tables["market"])
    if later_feeds:
        from actuarycanary.synthetic.check_phase2 import check_later_feeds

        found += check_later_feeds(reader, tables)
    return found


def _schema(reader: _Reader, feed: str, frame: pl.DataFrame) -> list[Violation]:
    """Required columns present, types as specified, classified values known."""
    out: list[Violation] = []
    fields = reader.spec[feed]["fields"]
    for field in fields:
        name = field["name"]
        if name not in frame.columns:
            if field["required"]:
                out.append(
                    Violation("SCHEMA", f"{feed}.xlsx", 1, f"required column {name} missing")
                )
            continue
        column = frame[name]
        if (
            field["type"] == "number"
            and not column.dtype.is_numeric()
            and column.null_count() < len(column)
        ):
            out.append(
                Violation(
                    "SCHEMA",
                    f"{feed}.xlsx",
                    len(column) - column.null_count(),
                    f"{name} is not numeric ({column.dtype})",
                )
            )
        if field["type"] == "text" and column.dtype not in (pl.String, pl.Null):
            out.append(
                Violation(
                    "SCHEMA",
                    f"{feed}.xlsx",
                    len(column),
                    f"{name} is not text ({column.dtype}); identifiers must survive as text",
                )
            )
        if (
            field["type"] == "date"
            and column.dtype != pl.Date
            and column.null_count() < len(column)
        ):
            out.append(
                Violation(
                    "SCHEMA",
                    f"{feed}.xlsx",
                    len(column) - column.null_count(),
                    f"{name} has values that are not dates",
                )
            )
    return out


def _valuations(reader: _Reader, v: pl.DataFrame, claims: pl.DataFrame | None) -> list[Violation]:
    f = "claim_valuations.xlsx"
    out: list[Violation] = []
    out += _count(
        "DV-CLV-01",
        f,
        v["claim_id"].is_null() | v["valuation_date"].is_null(),
        "claim_id or valuation_date missing",
    )
    out += _count(
        "DV-CLV-02",
        f,
        v["paid_to_date"].is_null() | v["case_reserve"].is_null() | v["status"].is_null(),
        "paid, reserve or status missing",
    )
    currency_ok = v["currency"].map_elements(
        lambda c: c is not None and bool(CURRENCY.match(str(c))),
        return_dtype=pl.Boolean,
        skip_nulls=False,
    )
    out += _count("DV-CLV-03", f, ~currency_ok, "currency empty or not an ISO code")
    status_ok = _class_ok(
        reader,
        "claim_valuations",
        "status",
        v["status"],
        ["OPEN", "CLOSED", "CLOSED_NIL", "REOPENED", "LITIGATED"],
    )
    out += _count(
        "DV-CLV-04",
        f,
        v["status"].is_not_null() & ~status_ok,
        "status label outside the dictionaries",
    )
    out += _count(
        "DV-CLV-05",
        f,
        v["valuation_date"].is_not_null()
        & (v["valuation_date"].dt.month_end() != v["valuation_date"]),
        "valuation_date is not a month end",
    )
    key = ["claim_id", "valuation_date"]
    out += _count(
        "DV-CLV-06", f, _extra_copies(v.select(key)), "repeated claim and valuation month"
    )
    ordered = v.with_row_index().unique(subset=key, keep="first", maintain_order=True).sort(key)
    falling = ordered.select(
        ((pl.col("paid_to_date").diff().over("claim_id")) < 0).fill_null(False)
    ).to_series()
    out += _count("DV-CLV-07", f, falling, "paid_to_date lower than at the previous valuation")
    amounts = [
        c for c in v.columns if c.endswith("_to_date") or c in ("case_reserve", "ceded_reserve")
    ]
    out += _count(
        "DV-CLV-08",
        f,
        v.select(pl.any_horizontal([pl.col(c) < 0 for c in amounts])).to_series().fill_null(False),
        "negative amount",
    )
    cls = _class_of(reader, "claim_valuations", "status", v["status"])
    closed = cls.is_in(["CLOSED", "CLOSED_NIL"])
    out += _count(
        "DV-CLV-09", f, closed & (v["case_reserve"] != 0), "closed claim with a case reserve"
    )
    out += _count(
        "DV-CLV-10",
        f,
        (cls == "CLOSED_NIL") & (v["paid_to_date"] != 0),
        "nil closure with a payment",
    )
    if "ceded_paid_to_date" in v.columns:
        out += _count(
            "DV-CLV-11",
            f,
            (v["ceded_paid_to_date"] > v["paid_to_date"])
            | (v["ceded_reserve"] > v["case_reserve"]),
            "ceded amount above gross",
        )
    several = (
        v.group_by("claim_id")
        .agg(pl.col("currency").drop_nulls().n_unique().alias("n"))
        .filter(pl.col("n") > 1)
    )
    out += _count("DV-CLV-12", f, several.height, "claims with more than one currency")
    months = (
        v.filter(pl.col("valuation_date").is_not_null())
        .select(
            "claim_id",
            (pl.col("valuation_date").dt.year() * 12 + pl.col("valuation_date").dt.month()).alias(
                "m"
            ),
        )
        .unique()
    )
    span = months.group_by("claim_id").agg(
        (pl.col("m").max() - pl.col("m").min() + 1).alias("span"),
        pl.col("m").n_unique().alias("have"),
    )
    out += _count(
        "DV-CLV-13",
        f,
        int((span["span"] - span["have"]).sum()),
        "months missing between first and last valuation",
    )
    if claims is not None:
        out += _count(
            "DV-CLV-14",
            f,
            v.select(~pl.col("claim_id").is_in(claims["claim_id"].implode())).to_series(),
            "claim_id not in claims",
        )
    return out


def _claims(
    reader: _Reader, c: pl.DataFrame, v: pl.DataFrame, policies: pl.DataFrame | None
) -> list[Violation]:
    f = "claims.xlsx"
    out: list[Violation] = []
    out += _count("DV-CLM-01", f, c["claim_id"].is_null(), "claim_id missing")
    out += _count("DV-CLM-02", f, _extra_copies(c.select("claim_id")), "repeated claim_id")
    out += _count(
        "DV-CLM-03",
        f,
        c.select(
            pl.any_horizontal(pl.col("occurrence_date", "report_date", "segment", "line").is_null())
        ).to_series(),
        "required field missing",
    )
    out += _count(
        "DV-CLM-04", f, c["occurrence_date"] > c["report_date"], "occurrence after report"
    )
    out += _count("DV-CLM-05", f, c["report_date"] > c["close_date"], "report after close")
    seg_ok = _class_ok(
        reader, "claims", "segment", c["segment"], ["NON_LIFE", "LIFE", "PENSION", "HEALTH"]
    )
    out += _count(
        "DV-CLM-06",
        f,
        c["segment"].is_not_null() & ~seg_ok,
        "segment label outside the dictionaries",
    )
    cut_off = v["valuation_date"].max()
    early, late = date(1950, 1, 1), cut_off
    bad = pl.any_horizontal(
        [
            (pl.col(n) < early) | (pl.col(n) > late)
            for n in ("occurrence_date", "report_date", "close_date")
        ]
    )
    out += _count(
        "DV-CLM-07",
        f,
        c.select(bad).to_series().fill_null(False),
        "date outside 1950 and the cut-off",
    )
    first = v.group_by("claim_id").agg(pl.col("valuation_date").min().alias("first_valuation"))
    joined = c.join(first, on="claim_id", how="left")
    month = lambda col: pl.col(col).dt.year() * 12 + pl.col(col).dt.month()  # noqa: E731
    out += _count(
        "DV-CLM-08",
        f,
        joined.select(month("report_date") > month("first_valuation")).to_series().fill_null(False),
        "reported after the first valuation month",
    )
    out += _count("DV-CLM-11", f, joined["first_valuation"].is_null(), "claim without valuations")
    if policies is not None:
        out += _count(
            "DV-CLM-09",
            f,
            c.select(
                pl.col("policy_id").is_not_null()
                & ~pl.col("policy_id").is_in(policies["policy_id"].implode())
            ).to_series(),
            "policy_id not in policies",
        )
        cover = c.join(
            policies.select("policy_id", "start_date", "end_date", "cancellation_date"),
            on="policy_id",
            how="inner",
        )
        stop = pl.min_horizontal(
            pl.col("end_date"), pl.col("cancellation_date").fill_null(date(2999, 1, 1))
        )
        out += _count(
            "DV-CLM-10",
            f,
            cover.select(
                (pl.col("occurrence_date") < pl.col("start_date"))
                | (pl.col("occurrence_date") >= stop)
            ).to_series(),
            "occurrence outside the policy's cover",
        )
    return out


def _policies(reader: _Reader, p: pl.DataFrame) -> list[Violation]:
    f = "policies.xlsx"
    out: list[Violation] = []
    out += _count("DV-POL-01", f, p["policy_id"].is_null(), "policy_id missing")
    out += _count("DV-POL-02", f, _extra_copies(p.select("policy_id")), "repeated policy_id")
    out += _count(
        "DV-POL-03",
        f,
        p.select(
            pl.any_horizontal(
                pl.col("start_date", "end_date", "segment", "line", "currency").is_null()
            )
        ).to_series(),
        "required field missing",
    )
    out += _count("DV-POL-04", f, p["start_date"] >= p["end_date"], "start not before end")
    out += _count(
        "DV-POL-05",
        f,
        p["cancellation_date"].is_not_null()
        & ((p["cancellation_date"] < p["start_date"]) | (p["cancellation_date"] > p["end_date"])),
        "cancellation outside cover",
    )
    out += _count(
        "DV-POL-06",
        f,
        p["currency"].map_elements(
            lambda c: c is None or not CURRENCY.match(str(c)),
            return_dtype=pl.Boolean,
            skip_nulls=False,
        ),
        "currency not an ISO code",
    )
    seg_ok = _class_ok(
        reader, "policies", "segment", p["segment"], ["NON_LIFE", "LIFE", "PENSION", "HEALTH"]
    )
    ch_ok = _class_ok(
        reader,
        "policies",
        "channel",
        p["channel"],
        ["AGENCY", "BROKER", "BANK", "DIRECT", "DIGITAL", "PARTNER"],
    )
    out += _count(
        "DV-POL-07",
        f,
        (p["segment"].is_not_null() & ~seg_ok) | (p["channel"].is_not_null() & ~ch_ok),
        "segment or channel outside the dictionaries",
    )
    out += _count(
        "DV-POL-08",
        f,
        (p["sum_insured"] < 0) | (p["exposure_units"] < 0),
        "negative sum insured or exposure",
    )
    return out


def _premiums(reader: _Reader, t: pl.DataFrame, policies: pl.DataFrame | None) -> list[Violation]:
    f = "premiums.xlsx"
    out: list[Violation] = []
    out += _count(
        "DV-PRM-01",
        f,
        t["transaction_id"].is_null() | t["policy_id"].is_null(),
        "transaction_id or policy_id missing",
    )
    out += _count(
        "DV-PRM-02", f, _extra_copies(t.select("transaction_id")), "repeated transaction_id"
    )
    out += _count(
        "DV-PRM-03",
        f,
        t.select(
            pl.any_horizontal(pl.col("booking_date", "amount", "currency", "type").is_null())
        ).to_series(),
        "required field missing",
    )
    classes = [
        "WRITTEN",
        "ENDORSEMENT",
        "CANCELLATION",
        "REFUND",
        "COMMISSION",
        "CEDED_PREMIUM",
        "RI_COMMISSION",
    ]
    type_ok = _class_ok(reader, "premiums", "type", t["type"], classes)
    out += _count(
        "DV-PRM-04", f, t["type"].is_not_null() & ~type_ok, "type outside the dictionaries"
    )
    out += _count(
        "DV-PRM-05",
        f,
        t["currency"].map_elements(
            lambda c: c is None or not CURRENCY.match(str(c)),
            return_dtype=pl.Boolean,
            skip_nulls=False,
        ),
        "currency not an ISO code",
    )
    cls = _class_of(reader, "premiums", "type", t["type"])
    signed = {
        "WRITTEN": 1,
        "COMMISSION": 1,
        "CEDED_PREMIUM": 1,
        "RI_COMMISSION": 1,
        "CANCELLATION": -1,
        "REFUND": -1,
    }
    for kind, sign in signed.items():
        amounts = t.filter(cls == kind)["amount"].drop_nulls()
        amounts = amounts.filter(amounts != 0)
        if len(amounts) and int(((amounts * sign) < 0).sum()) * 2 > len(amounts):
            out.append(Violation("DV-PRM-08", f, len(amounts), f"{kind} carries the opposite sign"))
    if policies is not None:
        out += _count(
            "DV-PRM-06",
            f,
            t.select(~pl.col("policy_id").is_in(policies["policy_id"].implode())).to_series(),
            "policy_id not in policies",
        )
        cover = t.join(
            policies.select("policy_id", "start_date", "end_date", "currency"),
            on="policy_id",
            how="inner",
            suffix="_policy",
        )
        eff = pl.col("effective_date").fill_null(pl.col("booking_date"))
        out += _count(
            "DV-PRM-07",
            f,
            cover.select((eff < pl.col("start_date")) | (eff > pl.col("end_date"))).to_series(),
            "effective date outside cover",
        )
        out += _count(
            "DV-PRM-09",
            f,
            cover["currency"] != cover["currency_policy"],
            "currency differs from the policy's",
        )
    return out


def _expenses(reader: _Reader, e: pl.DataFrame) -> list[Violation]:
    f = "expenses.xlsx"
    out: list[Violation] = []
    out += _count(
        "DV-EXP-01",
        f,
        e.select(pl.any_horizontal(pl.col("period", "amount", "type").is_null())).to_series(),
        "period, amount or type missing",
    )
    out += _count(
        "DV-EXP-02",
        f,
        e["currency"].map_elements(
            lambda c: c is None or not CURRENCY.match(str(c)),
            return_dtype=pl.Boolean,
            skip_nulls=False,
        ),
        "currency not an ISO code",
    )
    type_ok = _class_ok(
        reader,
        "expenses",
        "type",
        e["type"],
        ["ACQUISITION", "ADMINISTRATION", "CLAIMS_HANDLING_UNALLOCATED", "OTHER"],
    )
    out += _count(
        "DV-EXP-03", f, e["type"].is_not_null() & ~type_ok, "type outside the dictionaries"
    )
    out += _count(
        "DV-EXP-04",
        f,
        e["period"].is_not_null() & (e["period"].dt.month_end() != e["period"]),
        "period is not a month end",
    )
    out += _count("DV-EXP-05", f, e["amount"] <= 0, "amount not positive")
    out += _count("DV-EXP-06", f, _extra_copies(e), "identical rows")
    return out


def _market(reader: _Reader, sheets: dict[str, pl.DataFrame]) -> list[Violation]:
    f = "market.xlsx"
    out: list[Violation] = []
    m = pl.concat(sheets.values())
    out += _count(
        "DV-MKT-01",
        f,
        m.select(pl.any_horizontal(pl.all().is_null())).to_series(),
        "a required value is missing",
    )
    kinds = _class_of(reader, "market", "kind", m["kind"])
    out += _count(
        "DV-MKT-05", f, m["kind"].is_not_null() & kinds.is_null(), "kind outside the dictionaries"
    )
    out += _count("DV-MKT-03", f, m["value"] <= 0, "value not positive")
    fx = kinds.is_in(["FX_SPOT", "FX_PERIOD_AVERAGE", "FX_PERIOD_END"])
    pair = m["series_id"].map_elements(
        lambda s: bool(PAIR.match(str(s))), return_dtype=pl.Boolean, skip_nulls=False
    )
    out += _count("DV-MKT-04", f, (fx & ~pair) | (~fx & pair), "series_id does not fit its kind")
    key = m.with_columns(kinds.alias("cls"), pl.col("date").dt.month_end().alias("month")).select(
        "series_id",
        "cls",
        pl.when(pl.col("cls") == "FX_SPOT")
        .then(pl.col("date"))
        .otherwise(pl.col("month"))
        .alias("when"),
    )
    out += _count(
        "DV-MKT-02", f, _extra_copies(key), "more than one value for a series, kind and date"
    )
    monthly = (
        m.with_columns(kinds.alias("cls"))
        .filter(pl.col("cls") != "FX_SPOT")
        .select(
            "series_id",
            "cls",
            (pl.col("date").dt.year() * 12 + pl.col("date").dt.month()).alias("n"),
        )
        .unique()
    )
    gaps = monthly.group_by("series_id", "cls").agg(
        (pl.col("n").max() - pl.col("n").min() + 1 - pl.col("n").n_unique()).alias("gap")
    )
    out += _count("DV-MKT-06", f, int(gaps["gap"].sum()), "months missing between first and last")
    return out
