"""MT21 against the generator's truth on the tiny reinsurance_heavy scenario, and CV09 on its
treaty-level movements.

Spec IDs proved: MT21, CV09.

The application with `index_clause = occurrence_date` (the generator's clause, record 0240)
applied to the simulated gross ultimate of each claim reproduces `reinsurance_by_claim.csv`:
quota share and surplus to the cent the truth is rounded to, per-claim excess of loss to the cent
(the treaty table rounds the indexed terms to cents), event excess of loss within 1 per cent per
treaty and contract year (record 0403). Claims not reported at the cut-off are in the truth but
not in the data, so they are left out.
"""

from dataclasses import replace
from datetime import date

import polars as pl
import pytest

from actuarycanary.convert.allocation import GIVEN, allocate
from actuarycanary.methods.reinsurance import (
    OCCURRENCE_DATE,
    PAYMENT_BY_PAYMENT,
    ClaimBook,
    apply_programme,
)
from actuarycanary.modules.reinsurance_inputs import apply, assemble

SCENARIO = "reinsurance_heavy"


@pytest.fixture(scope="module")
def heavy(scenario_checked, scenario_folder):
    feeds, _ = scenario_checked(SCENARIO)
    frames = {concept: feed.frame for concept, feed in feeds.items()}
    truth = pl.read_csv(
        scenario_folder(SCENARIO) / "truth" / "reinsurance_by_claim.csv",
        schema_overrides={"claim_id": pl.String},
    )
    return frames, truth


def test_the_application_reproduces_the_generator(heavy) -> None:
    frames, truth = heavy
    inputs = assemble(frames, OCCURRENCE_DATE)
    assert inputs.book is not None and not inputs.excluded
    reported = set(inputs.book.claims["claim_id"].to_list())
    gross = (
        truth.filter(pl.col("claim_id").is_in(list(reported)))
        .group_by("claim_id")
        .agg(pl.col("gross_ultimate").first())
    )
    assert truth["claim_id"].n_unique() - gross.height <= 3  # a few claims are not reported yet
    ultimate = ClaimBook(
        gross.select(
            "claim_id",
            pl.lit(date(2099, 12, 31)).alias("valuation_date"),
            pl.col("gross_ultimate").alias("paid"),
            pl.col("gross_ultimate").alias("incurred"),
        ),
        inputs.book.claims,
        inputs.book.policies,
    )
    app = apply_programme(inputs.sections, ultimate, inputs.options)
    mine = app.ceded.group_by(["claim_id", "treaty_id"]).agg(pl.col("ceded_paid").sum())
    joined = (
        truth.filter(pl.col("claim_id").is_in(list(reported)))
        .join(mine, on=["claim_id", "treaty_id"], how="full", coalesce=True)
        .with_columns(pl.col("ceded_paid").fill_null(0.0), pl.col("ceded_ultimate").fill_null(0.0))
        .with_columns((pl.col("ceded_paid") - pl.col("ceded_ultimate")).abs().alias("gap"))
    )
    proportional = joined.filter(pl.col("treaty_id").str.contains("^(QS|SURPLUS)_"))
    assert proportional.height > 50
    assert (proportional["gap"] <= 0.005 + 1e-9 * proportional["ceded_ultimate"].abs()).all()
    risk = joined.filter(
        pl.col("treaty_id").is_in(["XL_OD_RISK", "XL_TPL_L1", "XL_TPL_L2", "XL_TPL_L3"])
    )
    assert risk.filter(pl.col("ceded_ultimate") > 0).height >= 10
    assert (risk["gap"] <= 0.01).all()
    event = joined.filter(pl.col("treaty_id") == "XL_PROPERTY_CAT")
    assert event["ceded_ultimate"].sum() == pytest.approx(
        event["ceded_paid"].sum(), rel=0.01, abs=1.0
    )


@pytest.fixture(scope="module")
def default_application(heavy):
    """The loaded programme on the scenario's claims under the default clause, once."""
    frames, _ = heavy
    inputs = assemble(frames)
    return inputs, apply(inputs)


def test_the_default_clause_differs_on_the_indexed_layers_only(heavy, default_application) -> None:
    frames, _ = heavy
    inputs, default = default_application
    wanted = {"QS_MOTOR_OD", "XL_TPL_L3"}
    sections = [s for s in inputs.sections if s.treaty_id in wanted]
    fixed = apply_programme(
        sections, inputs.book, replace(inputs.options, index_clause=OCCURRENCE_DATE)
    )
    totals = {}
    for clause, app in ((PAYMENT_BY_PAYMENT, default), (OCCURRENCE_DATE, fixed)):
        assert app is not None
        totals[clause] = dict(
            app.ceded_at().group_by("treaty_id").agg(pl.col("ceded_incurred").sum()).iter_rows()
        )
    # a quota share has no layer: the clause changes nothing; an indexed layer moves
    assert totals[PAYMENT_BY_PAYMENT]["QS_MOTOR_OD"] == pytest.approx(
        totals[OCCURRENCE_DATE]["QS_MOTOR_OD"]
    )
    assert totals[PAYMENT_BY_PAYMENT]["XL_TPL_L3"] != pytest.approx(
        totals[OCCURRENCE_DATE]["XL_TPL_L3"]
    )


def test_every_movement_adds_up_and_quota_share_premium_follows_written_premium(
    default_application,
) -> None:
    inputs, app = default_application
    assert inputs.movements is not None
    allocation = allocate(inputs.movements, inputs.sections, inputs.book, app, inputs.written).rows
    sums = (
        allocation.group_by("transaction_id")
        .agg(pl.col("amount").sum())
        .join(
            inputs.movements.select("transaction_id", pl.col("amount").alias("booked")),
            on="transaction_id",
        )
    )
    assert sums.height == inputs.movements.height
    assert float((sums["amount"] - sums["booked"]).abs().max()) < 0.005  # type: ignore[arg-type]  # cent
    # claim movements of the generator carry their claim: taken as given (CV09 precedence)
    claims = allocation.filter(pl.col("type").is_in(["CEDED_CLAIM_PAID", "CEDED_CASE_RESERVE"]))
    assert claims["method"].unique().to_list() == [GIVEN]
    # the generator cedes 40 % of each written premium of MOTOR_OD: so does the allocation
    assert inputs.written is not None
    qs = allocation.filter(
        (pl.col("treaty_id") == "QS_MOTOR_OD") & (pl.col("type") == "CEDED_PREMIUM")
    )
    written = (
        inputs.written.filter(pl.col("policy_id").is_in(qs["policy_id"].unique().to_list()))
        .filter(pl.col("booking_date") >= date(2022, 1, 1))
        .group_by("policy_id")
        .agg(pl.col("amount").sum().alias("gross"))
    )
    ratio = qs.group_by("policy_id").agg(pl.col("amount").sum()).join(written, on="policy_id")
    ratio = ratio.filter(pl.col("gross").abs() > 100)
    assert float(((ratio["amount"] / ratio["gross"]) - 0.4).abs().max()) < 1e-3  # type: ignore[arg-type]
