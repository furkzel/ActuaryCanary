"""Scenario files: validated parameters of the simulated insurer.

A scenario file may start from another one with ``extends: <name>``; dictionaries merge
key by key, every other value (lists included) replaces the inherited one.
"""

from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

SCENARIO_FOLDER = Path("synthetic") / "scenarios"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class Dist(_Strict):
    """A one-dimensional distribution; which parameters are needed depends on ``dist``."""

    dist: Literal["lognormal", "gamma", "fixed", "poisson", "fixed_share_of_sum_insured"]
    median: float | None = None
    sigma: float | None = None
    mean: float | None = None
    cv: float | None = None
    value: float | None = None
    min: float | None = None
    share: float | None = None

    @model_validator(mode="after")
    def _needs(self) -> "Dist":
        needed = {
            "lognormal": ("median", "sigma"),
            "gamma": ("mean", "cv"),
            "fixed": ("value",),
            "poisson": ("mean",),
            "fixed_share_of_sum_insured": ("share",),
        }[self.dist]
        missing = [name for name in needed if getattr(self, name) is None]
        if missing:
            raise ValueError(f"{self.dist} needs {', '.join(missing)}")
        return self


class Tail(_Strict):
    probability: float = Field(ge=0, le=1)
    dist: Literal["pareto"]
    threshold: float = Field(gt=0)
    alpha: float = Field(gt=0)


class Portfolio(_Strict):
    policies_first_year: int = Field(ge=1)
    growth_per_year: float
    term_months: int = Field(ge=1)
    foreign_currency_share: float = Field(ge=0, le=1)
    foreign_currencies: dict[str, float] = {}
    exposure_units: Dist = Dist(dist="fixed", value=1.0)
    sum_insured: Dist
    cancellation_probability: float = Field(ge=0, le=1)


class Premium(_Strict):
    rate_on_sum_insured: float | None = None
    per_policy: float | None = None
    indexed_to: str
    commission_rate: float = Field(ge=0, le=1)
    endorsement_probability: float = Field(default=0.0, ge=0, le=1)
    refund_probability: float = Field(default=0.0, ge=0, le=1)

    @model_validator(mode="after")
    def _one_basis(self) -> "Premium":
        if (self.rate_on_sum_insured is None) == (self.per_policy is None):
            raise ValueError("give exactly one of rate_on_sum_insured and per_policy")
        return self


class Frequency(_Strict):
    per_exposure_year: float = Field(ge=0)
    trend_per_year: float = 0.0


class Severity(_Strict):
    body: Dist
    tail: Tail | None = None
    superimposed_inflation: float = 0.0
    capped_at_sum_insured: bool = False


class Payments(_Strict):
    count: Dist


class CaseReserve(_Strict):
    initial_bias: float
    noise_sigma: float = Field(ge=0)
    review_every_months: int = Field(ge=1)


class Litigation(_Strict):
    probability: float = Field(ge=0, le=1)
    severity_multiplier: float = Field(gt=0)
    settlement_delay_multiplier: float = Field(gt=0)


class Recovery(_Strict):
    probability: float = Field(ge=0, le=1)
    recovered_share: float = Field(ge=0, le=1)
    delay_days: Dist


class Recoveries(_Strict):
    subrogation: Recovery | None = None
    salvage: Recovery | None = None


class CatEvent(_Strict):
    event_code: str
    date: date
    claims: int = Field(ge=1)
    severity_multiplier: float = Field(gt=0)


class LargeEvents(_Strict):
    """Very large single claims on top of the regular process, at a rate per exposure year, so
    that their number grows with the portfolio. Cost at base-date prices, no cap."""

    per_exposure_year: float = Field(gt=0)
    cost: Dist
    label: str = "LARGE_LOSS_EVENT"


class Line(_Strict):
    segment: Literal["NON_LIFE", "LIFE", "PENSION", "HEALTH"]
    entities: list[str] = Field(min_length=1)
    products: dict[str, float]
    causes: dict[str, float]
    portfolio: Portfolio
    premium: Premium
    frequency: Frequency
    severity: Severity
    reporting_delay_days: Dist
    settlement_delay_days: Dist
    payments: Payments
    case_reserve: CaseReserve
    nil_close_probability: float = Field(ge=0, le=1)
    reopen_probability: float = Field(ge=0, le=1)
    litigation: Litigation | None = None
    recoveries: Recoveries = Recoveries()
    allocated_expense_share: float = Field(ge=0)
    catastrophe_events: list[CatEvent] = []
    large_events: LargeEvents | None = None


class Treaty(_Strict):
    treaty_id: str
    type: Literal["QUOTA_SHARE", "EXCESS_OF_LOSS"]
    lines: list[str] = Field(min_length=1)
    basis: Literal["claim", "event"] = "claim"
    cession: float | None = None
    commission: float | None = None
    retention: float | None = None
    limit: float | None = None
    retention_indexed_to: str | None = None
    rate_on_gross_premium: float | None = None
    inception: date
    renewal: Literal["annual"] = "annual"

    @model_validator(mode="after")
    def _terms(self) -> "Treaty":
        if self.type == "QUOTA_SHARE" and self.cession is None:
            raise ValueError("a quota share needs cession")
        if self.type == "EXCESS_OF_LOSS" and (self.retention is None or self.limit is None):
            raise ValueError("an excess of loss needs retention and limit")
        return self


class Fx(_Strict):
    series_id: str
    start: float = Field(gt=0)
    drift: Literal["inflation_differential"]
    foreign_inflation: float
    monthly_vol: float = Field(ge=0)


class Cpi(_Strict):
    series_id: str
    base_value: float = Field(gt=0)
    annual_rate_by_year: dict[int, float]
    monthly_noise_sd: float = Field(ge=0)
    future_annual_rate: float | None = None


class Market(_Strict):
    cpi: Cpi
    fx: list[Fx]
    fx_kinds_written: list[Literal["FX_SPOT", "FX_PERIOD_AVERAGE", "FX_PERIOD_END"]]


class Period(_Strict):
    start: date
    end: date


class Valuation(_Strict):
    first: date
    last: date
    frequency: Literal["month_end"]


class Meta(_Strict):
    version: int
    seed: int
    base_date: date
    accident_period: Period
    valuation: Valuation
    reporting_currency: str
    max_settlement_days: int = Field(ge=30)


class Entity(_Strict):
    id: str
    name: str
    segments: list[str]


class Partner(_Strict):
    id: str
    channel: Literal["AGENCY", "BROKER", "BANK", "DIRECT", "DIGITAL", "PARTNER"]
    share: float = Field(gt=0)


class Expenses(_Strict):
    administration_share: dict[str, float]
    acquisition_share: dict[str, float]
    other_share_of_earned: float = Field(ge=0)
    unallocated_claims_handling_share_of_paid: float = Field(ge=0)


class PracticeChange(_Strict):
    line: str
    from_: date = Field(alias="from")
    initial_bias: float


class LargeClaim(_Strict):
    line: str
    date: date
    cost_base: float = Field(gt=0)
    label: str = "LARGE_LOSS_SHOCK"


class Faults(_Strict):
    duplicate_valuation_rows: int = Field(ge=0)
    report_before_occurrence: int = Field(ge=0)
    paid_to_date_decreasing_without_recovery: int = Field(ge=0)
    extreme_payment_outliers: int = Field(ge=0)
    missing_currency: int = Field(ge=0)
    unknown_status_labels: int = Field(ge=0)


class HeaderMess(_Strict):
    style: Literal["canonical", "aliases"] = "canonical"
    canonical_share: float = Field(default=0.2, ge=0, le=1)  # share of headers left canonical
    misspell_share: float = Field(default=0.0, ge=0, le=1)


class TitleRows(_Strict):
    min: int = Field(default=0, ge=0)
    max: int = Field(default=0, ge=0)


class DateMess(_Strict):
    text_share: float = Field(default=0.0, ge=0, le=1)  # share of date cells written as text


class LabelMess(_Strict):
    translate_share: float = Field(default=0.0, ge=0, le=1)  # share of labels given as aliases


class Messiness(_Strict):
    headers: HeaderMess = HeaderMess()
    title_rows: TitleRows = TitleRows()
    date_formats: DateMess = DateMess()
    value_labels: LabelMess = LabelMess()
    exact_duplicate_share: float = Field(default=0.0, ge=0, le=1)
    personal_data: bool = False


class PersonalColumn(_Strict):
    name: str
    kind: Literal["name", "national_id_11_digits", "customer_number"]


class SizeSpec(_Strict):
    portfolio_scale: float = Field(gt=0)
    years: tuple[int, int] | None = None
    exposure_multiplier: dict[str, float] = {}  # persons per group policy etc.; keeps loss ratios
    fault_scale: float = Field(default=1.0, gt=0)  # injected fault counts are multiplied by this


# --- phase 2 feeds -------------------------------------------------------------------------
# Parameters of the feeds added after version 1.0 live under one key, ``phase2``. The key is left
# out of ``truth/scenario.yaml`` (the file of earlier scenarios stays byte for byte the same) and
# written to ``truth/phase2_scenario.yaml`` instead.


class SurplusTreaty(_Strict):
    """A surplus treaty: the insurer keeps a line per risk, reinsurers take up to
    ``number_of_lines`` further lines. The ceded share of a policy is fixed by its sum insured
    at the policy start."""

    treaty_id: str
    lines: list[str] = Field(min_length=1)
    retained_line: float = Field(gt=0)  # TRY at base-date prices
    number_of_lines: float = Field(gt=0)
    retention_indexed_to: str | None = None
    commission: float | None = None
    inception: date
    renewal: Literal["annual"] = "annual"


class CurveSpec(_Strict):
    curve_id: str
    currency: str


class Rates(_Strict):
    """Yield curves consistent with each scenario's inflation path: the spot rate to tenor T is the
    real rate, plus the inflation expected over the next T years (the scenario's own path), plus a
    term premium that grows with the tenor, plus a slowly moving shock."""

    curves: list[CurveSpec] = [
        CurveSpec(curve_id="TRY_GOV", currency="TRY"),
        CurveSpec(curve_id="USD_TSY", currency="USD"),
        CurveSpec(curve_id="EUR_SWAP", currency="EUR"),
    ]
    tenors_months: list[int] = [3, 12, 24, 36, 60, 84, 120]
    real_rate: float = 0.015
    term_premium: float = 0.01
    term_premium_scale_years: float = 5.0
    noise_sd: float = 0.002
    noise_persistence: float = Field(default=0.9, ge=0, lt=1)
    source: str = "SYNTHETIC"

    @model_validator(mode="after")
    def _one_year_tenor(self) -> "Rates":
        if 12 not in self.tenors_months:
            raise ValueError("the tenors must include 12 months (the life book credits at it)")
        return self


class LedgerDifferences(_Strict):
    """Reconciliation differences written into the ledger on purpose (and into the truth)."""

    premium_timing_months: int = Field(default=2, ge=0)  # a month of premium booked a month late
    unmapped_account: bool = True  # an account with a balance that the mapping profile lacks
    outstanding_with_ibnr_share: float = Field(default=0.08, ge=0)  # one entity books IBNR too
    translation_months: int = Field(default=1, ge=0)  # foreign premium at a wrong rate
    missing_months: int = Field(default=1, ge=0)  # an account row left out for one month


class LedgerParams(_Strict):
    fiscal_year_start_month: int = Field(default=1, ge=1, le=12)
    differences: LedgerDifferences = LedgerDifferences()
    other_income_share_of_written: float = Field(default=0.002, ge=0)


class LifeProduct(_Strict):
    """One life or pension product. Counts are per accident year at portfolio_scale 1."""

    key: str
    line: str
    segment: Literal["LIFE", "PENSION"] = "LIFE"
    policy_type: Literal["INDIVIDUAL", "GROUP"] = "INDIVIDUAL"
    channel: Literal["AGENCY", "BROKER", "BANK", "DIRECT", "DIGITAL", "PARTNER"] = "AGENCY"
    contracts_first_year: int = Field(ge=1)
    growth_per_year: float = 0.0
    entry_age_mean: float = Field(gt=0)
    entry_age_sd: float = Field(gt=0)
    entry_age_min: int = 18
    entry_age_max: int = 70
    term_years: int | None = None  # None: runs until a decrement (whole life, group renewal)
    age_band_width: int = Field(default=1, ge=1)  # 1: the exact age; 5: a band such as 40-44
    sum_assured: Dist | None = None
    premium_rate: float = Field(default=0.0, ge=0)  # annual premium as a share of sum assured
    annual_contribution: Dist | None = None  # savings and pension products
    premium_frequency: Literal["MONTHLY", "QUARTERLY", "HALF_YEARLY", "YEARLY", "SINGLE"] = "YEARLY"
    mortality_multiplier: float = Field(gt=0)
    lapse_by_policy_year: list[float]  # annual rate of the reference table; the last holds on
    lapse_multiplier: float = Field(default=1.0, gt=0)  # true rate = reference rate times this
    lapse_decrement: Literal["LAPSE", "SURRENDER"] = "LAPSE"
    reinstatement_probability: float = Field(default=0.0, ge=0, le=1)
    partial_withdrawal_rate: float = Field(default=0.0, ge=0)  # per contract-year, savings
    transfer_out_rate: float = Field(default=0.0, ge=0)  # per contract-year, pension
    transfer_in_share: float = Field(default=0.0, ge=0, le=1)  # of new pension contracts
    fund_fee_rate: float = Field(default=0.0, ge=0)  # annual, on the fund value
    state_contribution_rate: float = Field(default=0.0, ge=0)  # on the member contribution
    employer_contribution_share: float = Field(default=0.0, ge=0, le=1)  # contracts with one
    has_fund: bool = False


class LifeMortality(_Strict):
    """Gompertz-Makeham force of mortality mu_x = a + b * c**x for the reference table."""

    a: float = Field(default=0.0006, ge=0)
    b: float = Field(default=0.00003, ge=0)
    c: float = Field(default=1.1, gt=1)
    male_factor: float = Field(default=1.10, gt=0)  # sex relative to the table; female is the rest
    female_factor: float = Field(default=0.90, gt=0)
    reporting_lag_days: Dist = Dist(dist="lognormal", median=12.0, sigma=0.8)
    table_max_age: int = 110


class LifeBook(_Strict):
    enabled: bool = False
    opening_years: int = Field(default=4, ge=0)  # years of entries before the first valuation
    opening_share: float = Field(default=0.7, ge=0, le=1)  # of those entries still in force then
    count_scale_by_size: dict[str, float] = {"tiny": 1.0, "medium": 1.0, "large": 1.0}
    mortality: LifeMortality = LifeMortality()
    fund_return_spread: float = 0.01  # fund return = one-year TRY rate minus this
    funds: list[str] = ["EQUITY", "BOND", "MONEY_MARKET"]
    switch_probability_per_year: float = Field(default=0.05, ge=0)
    products: list[LifeProduct] = []

    @model_validator(mode="after")
    def _products(self) -> "LifeBook":
        keys = [p.key for p in self.products]
        if len(set(keys)) != len(keys):
            raise ValueError("life product keys must be unique")
        if self.enabled and not self.products:
            raise ValueError("an enabled life book needs products")
        problems = [
            f"life product {p.key}: a reinstated contract cannot have a fund"
            for p in self.products
            if p.has_fund and p.reinstatement_probability > 0
        ]
        problems += [
            f"life product {p.key}: a fund product needs annual_contribution"
            for p in self.products
            if p.has_fund and p.annual_contribution is None
        ]
        if problems:
            raise ValueError("; ".join(problems))
        return self


class Phase2(_Strict):
    surplus: list[SurplusTreaty] = []
    rates: Rates = Rates()
    ledger: LedgerParams = LedgerParams()
    life_book: LifeBook = LifeBook()


class Scenario(_Strict):
    name: str = ""
    meta: Meta
    entities: list[Entity]
    partners: list[Partner]
    market: Market
    lines: dict[str, Line]
    reinsurance: list[Treaty] = []
    expenses: Expenses
    reserving_practice_changes: list[PracticeChange] = []
    large_claims: list[LargeClaim] = []
    injected_faults: Faults
    messiness: Messiness = Messiness()
    personal_data_columns: list[PersonalColumn] = []
    phase2: Phase2 = Phase2()
    sizes: dict[str, SizeSpec]

    @model_validator(mode="after")
    def _references(self) -> "Scenario":
        entity_ids = {e.id for e in self.entities}
        problems: list[str] = []
        for name, line in self.lines.items():
            problems += [
                f"line {name}: unknown entity {e}" for e in line.entities if e not in entity_ids
            ]
        for treaty in self.reinsurance:
            problems += [
                f"treaty {treaty.treaty_id}: unknown line {n}"
                for n in treaty.lines
                if n not in self.lines
            ]
        for surplus in self.phase2.surplus:
            problems += [
                f"surplus {surplus.treaty_id}: unknown line {n}"
                for n in surplus.lines
                if n not in self.lines
            ]
        problems += [
            f"practice change: unknown line {c.line}"
            for c in self.reserving_practice_changes
            if c.line not in self.lines
        ]
        problems += [
            f"large claim: unknown line {c.line}"
            for c in self.large_claims
            if c.line not in self.lines
        ]
        if problems:
            raise ValueError("; ".join(problems))
        return self


def find_scenario_dir(start: Path | None = None) -> Path:
    """Walk up from `start` (default: this file) to the first folder with synthetic/scenarios/."""
    here = (start or Path(__file__)).resolve()
    for folder in (here, *here.parents):
        candidate = folder / SCENARIO_FOLDER
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(f"{SCENARIO_FOLDER.as_posix()} not found above {here}")


def merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge two mappings; values in `over` win, lists are replaced, not joined."""
    merged = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _read_raw(name: str, folder: Path, seen: tuple[str, ...] = ()) -> dict[str, Any]:
    if name in seen:
        raise ValueError(
            f"scenario files extend each other in a loop: {' -> '.join((*seen, name))}"
        )
    path = folder / f"{name}.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    parent = raw.pop("extends", None)
    if parent is None:
        return raw
    return merge(_read_raw(parent, folder, (*seen, name)), raw)


def list_scenarios(folder: Path | None = None) -> list[str]:
    return sorted(p.stem for p in (folder or find_scenario_dir()).glob("*.yaml"))


def load_scenario(name: str, folder: Path | None = None) -> Scenario:
    """Read and validate scenario `name` (a file stem in synthetic/scenarios/)."""
    folder = folder or find_scenario_dir()
    return Scenario.model_validate({**_read_raw(name, folder), "name": name})


def load_with(name: str, overrides: dict[str, Any], folder: Path | None = None) -> Scenario:
    """Scenario `name` with `overrides` merged on top, as a scenario file with `extends` would."""
    folder = folder or find_scenario_dir()
    return Scenario.model_validate({**merge(_read_raw(name, folder), overrides), "name": name})


def sized(scenario: Scenario, size: str | SizeSpec) -> SizeSpec:
    """Resolve a size name (tiny, medium, large) or pass a custom size through."""
    if isinstance(size, SizeSpec):
        return size
    if size not in scenario.sizes:
        raise KeyError(f"unknown size {size!r}; the scenario has {sorted(scenario.sizes)}")
    return scenario.sizes[size]
