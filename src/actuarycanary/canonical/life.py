"""The canonical rules of the life feeds (records 0441, 0442): life_in_force (DV-LIF), life_events
(DV-LEV) and fund_flows (DV-FFL).

The rules that decide which rows enter a feed are applied here and reported; the rules that
compare rows of a contract over time or two feeds are checked by the quality report
(`quality/checks_life.py`) and applied by the exposure (`life/exposure.py`).

Age arrives as one whole age ("45"), a band of whole years ("45-49") or an open top band ("85+");
`age_low` and `age_high` hold the parsed ages (`age_high` empty for an open band). CV11 uses the
lower age for the arithmetic and keeps the band for grouping. Amounts are kept as given: a
negative amount is listed by DV-LEV-09 and DV-FFL-07 (a reversal), a fund switch is positive
into its fund and negative out of it (DV-FFL-06).
"""

import polars as pl

from actuarycanary.canonical.feeds import (
    UNKNOWN,
    UNMAPPED,
    Finding,
    _invalid_currency,
    _one_per_key,
    _unmapped_labels,
    finding,
)
from actuarycanary.io.excel import SOURCE_ROW
from actuarycanary.spec.models import DataConceptSpec

MAX_AGE = 120
AGE_LOW, AGE_HIGH = "age_low", "age_high"  # parsed from age_band (DV-LIF-03)
_BAND = r"^(\d{1,3})(?:-(\d{1,3})|(\+))?$"


def parse_age_band(band: pl.Expr) -> tuple[pl.Expr, pl.Expr, pl.Expr]:
    """(lower age, upper age, valid) of an age_band text: "45", "45-49" or "45+" (open, no upper
    age). Spaces are ignored; valid means the shape fits and 0 <= lower <= upper <= 120."""
    text = band.str.replace_all(r"\s", "")
    low = text.str.extract(_BAND, 1).cast(pl.Int64, strict=False)
    high_text = text.str.extract(_BAND, 2)
    open_band = text.str.extract(_BAND, 3).is_not_null()
    high = pl.when(open_band).then(None).otherwise(high_text.cast(pl.Int64, strict=False))
    high = pl.when(high_text.is_null() & ~open_band).then(low).otherwise(high)
    valid = (
        low.is_not_null()
        & (low <= MAX_AGE)
        & (open_band | (high.is_not_null() & (high >= low) & (high <= MAX_AGE)))
    )
    return low, high, valid.fill_null(False)


def _missing(frame: pl.DataFrame, required: tuple[str, ...]) -> pl.Expr:
    return pl.any_horizontal(pl.col(c).is_null() for c in required)


def _excluded(
    frame: pl.DataFrame, concept: str, rule: str, severity: str, message: str, bad: pl.Expr
) -> tuple[pl.DataFrame, Finding | None]:
    return frame.filter(~bad), finding(concept, rule, severity, message, frame.filter(bad))


def life_in_force_rules(
    frame: pl.DataFrame, spec: DataConceptSpec
) -> tuple[pl.DataFrame, list[Finding | None]]:
    concept = spec.id
    required = ("contract_id", "valuation_date", "entry_date", "age_band", "status")
    frame, missing = _excluded(
        frame,
        concept,
        "DV-LIF-01",
        "BLOCKING",
        "rows without contract_id, valuation_date, entry_date, age_band or status excluded "
        "from every study",
        _missing(frame, required),
    )
    found: list[Finding | None] = [missing]
    classified = ("status", "segment", "policy_type", "channel", "premium_frequency", "sex")
    frame, unmapped = _unmapped_labels(
        frame, spec, classified, "DV-LIF-02", f"; a row with an {UNMAPPED} status is excluded"
    )
    found.append(unmapped)
    frame = frame.filter(pl.col("status") != UNMAPPED)  # listed by the finding above
    low, high, valid = parse_age_band(pl.col("age_band"))
    frame = frame.with_columns(low.alias(AGE_LOW), high.alias(AGE_HIGH), valid.alias("_valid"))
    frame, bad_age = _excluded(
        frame,
        concept,
        "DV-LIF-03",
        "WARNING",
        'age_band is not one age, a band "x-y" or an open band "x+" between 0 and 120: '
        "rows excluded",
        ~pl.col("_valid"),
    )
    found.append(bad_age)
    frame, backwards = _excluded(
        frame.drop("_valid"),
        concept,
        "DV-LIF-04",
        "WARNING",
        "rows whose entry_date is after valuation_date excluded",
        pl.col("entry_date") > pl.col("valuation_date"),
    )
    found.append(backwards)
    frame, duplicates = _one_per_key(
        frame, concept, "DV-LIF-05", ["contract_id", "valuation_date"], "later"
    )
    return frame.sort(SOURCE_ROW), [*found, *duplicates]


def life_events_rules(
    frame: pl.DataFrame, spec: DataConceptSpec
) -> tuple[pl.DataFrame, list[Finding | None]]:
    concept = spec.id
    required = ("event_id", "contract_id", "event_date", "event_type")
    frame, missing = _excluded(
        frame,
        concept,
        "DV-LEV-01",
        "BLOCKING",
        "rows without event_id, contract_id, event_date or event_type excluded",
        _missing(frame, required),
    )
    frame, unmapped = _unmapped_labels(
        frame, spec, ("event_type",), "DV-LEV-02", "; such an event enters no rate"
    )
    frame, duplicates = _one_per_key(frame, concept, "DV-LEV-03", ["event_id"], "later")
    return frame.sort(SOURCE_ROW), [missing, unmapped, *duplicates]


def fund_flows_rules(
    frame: pl.DataFrame, spec: DataConceptSpec
) -> tuple[pl.DataFrame, list[Finding | None]]:
    concept = spec.id
    required = ("flow_id", "contract_id", "flow_date", "amount", "flow_type")
    frame, missing = _excluded(
        frame,
        concept,
        "DV-FFL-01",
        "BLOCKING",
        "rows without flow_id, contract_id, flow_date, amount or flow_type excluded",
        _missing(frame, required),
    )
    frame, unmapped = _unmapped_labels(
        frame, spec, ("flow_type",), "DV-FFL-02", "; such a flow is left out of LF04"
    )
    invalid = _invalid_currency()
    currency = finding(
        concept,
        "DV-FFL-03",
        "WARNING",
        f"empty or invalid currency becomes {UNKNOWN}: kept in original-currency views, "
        "excluded from converted views",
        frame.filter(invalid),
    )
    frame = frame.with_columns(
        pl.when(invalid).then(pl.lit(UNKNOWN)).otherwise(pl.col("currency")).alias("currency")
    )
    frame, duplicates = _one_per_key(frame, concept, "DV-FFL-04", ["flow_id"], "later")
    return frame.sort(SOURCE_ROW), [missing, unmapped, currency, *duplicates]


RULES = {
    "life_in_force": life_in_force_rules,
    "life_events": life_events_rules,
    "fund_flows": fund_flows_rules,
}
