"""MT21 application step and the CV09 scope rules on the twelve-claim hand fixture, and the
properties of the application.

Spec IDs proved: MT21, CV09.
"""

from datetime import date

import polars as pl
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from actuarycanary.methods.reinsurance import (
    OCCURRENCE_DATE,
    PAYMENT_BY_PAYMENT,
    ClaimBook,
    Options,
    Section,
    apply_programme,
    price_indices,
    sections_from_frame,
)
from actuarycanary.methods.reinsurance.application import EVENT_PER_CLAIM
from tests.benchmarks.load import load_reference, load_table

YEAR = {"inception": date(2020, 1, 1), "expiry": date(2021, 1, 1), "currency": "TRY"}
CUT = date(2020, 12, 31)


def _fixture() -> tuple[list[dict[str, str]], dict]:
    ref = load_reference("MT21-reinsurance-twelve-claims")
    return load_table(ref["folder"] / "claims.csv"), ref["values"]


def _book(claims: list[dict[str, str]], amounts: dict[str, float] | None = None) -> ClaimBook:
    ids = [r["claim_id"] for r in claims]
    gross = [
        amounts[i] if amounts else float(r["gross_loss"]) for i, r in zip(ids, claims, strict=True)
    ]
    return ClaimBook(
        valuations=pl.DataFrame(
            {"claim_id": ids, "valuation_date": [CUT] * len(ids), "paid": gross, "incurred": gross}
        ),
        claims=pl.DataFrame(
            {
                "claim_id": ids,
                "occurrence_date": [date(2020, 6, 1)] * len(ids),
                "policy_id": ids,
                "event_code": [r.get("event_code") or None for r in claims],
                "currency": ["TRY"] * len(ids),
            },
            schema_overrides={"event_code": pl.String},
        ),
        policies=pl.DataFrame(
            {
                "policy_id": ids,
                "start_date": [date(2020, 1, 1)] * len(ids),
                "sum_insured": [float(r["sum_insured"]) for r in claims],
                "currency": ["TRY"] * len(ids),
            }
        ),
    )


SURPLUS = Section("SP", "SURPLUS", retention=400, number_of_lines=4, **YEAR)
QUOTA = Section("QS", "QUOTA_SHARE", cession_share=0.3, **YEAR)
RISK_XL = Section("XL", "EXCESS_OF_LOSS", retention=100, limit=200, **YEAR)
EVENT_XL = Section("CAT", "EXCESS_OF_LOSS", loss_basis="EVENT", retention=120, limit=150, **YEAR)
STOP = Section("SL", "STOP_LOSS", loss_basis="AGGREGATE", retention=0.6, limit=0.3, **YEAR)


def _ceded(app, treaty: str) -> dict[str, float]:
    rows = app.ceded.filter(pl.col("treaty_id") == treaty)
    return dict(zip(rows["claim_id"].to_list(), rows["ceded_paid"].to_list(), strict=True))


def _check(values: dict, quantity: str, got: dict[str, float], ids: list[str]) -> None:
    for cid in ids:
        expected = values[(quantity, cid)]["value"]
        assert got.get(cid, 0.0) == pytest.approx(expected, rel=1e-12, abs=1e-12), (quantity, cid)


def test_each_treaty_alone_on_gross() -> None:
    claims, values = _fixture()
    ids = [r["claim_id"] for r in claims]
    book = _book(claims)
    for section, quantity in (
        (QUOTA, "quota_share_ceded"),
        (SURPLUS, "surplus_ceded"),
        (RISK_XL, "excess_of_loss_ceded"),
        (EVENT_XL, "event_excess_of_loss_ceded"),
    ):
        _check(values, quantity, _ceded(apply_programme([section], book), section.treaty_id), ids)
    stop = apply_programme([STOP], book, Options(earned_premium={STOP.key: 6000.0}))
    _check(values, "stop_loss_ceded", _ceded(stop, "SL"), ids)


def test_programme_in_the_inuring_order() -> None:
    claims, values = _fixture()
    ids = [r["claim_id"] for r in claims]
    # given in another order on purpose: the stages decide the order (CV09)
    app = apply_programme(
        [STOP, EVENT_XL, RISK_XL, QUOTA, SURPLUS],
        _book(claims),
        Options(earned_premium={STOP.key: 1000.0}),
    )
    _check(values, "programme_surplus_ceded", _ceded(app, "SP"), ids)
    _check(values, "programme_quota_share_ceded", _ceded(app, "QS"), ids)
    _check(values, "programme_excess_of_loss_ceded", _ceded(app, "XL"), ids)
    _check(values, "full_programme_event_excess_of_loss_ceded", _ceded(app, "CAT"), ids)
    _check(values, "full_programme_stop_loss_ceded", _ceded(app, "SL"), ids)
    net = dict(zip(app.net["claim_id"].to_list(), app.net["net_paid"].to_list(), strict=True))
    _check(values, "full_programme_net", net, ids)


def test_scope_rules_and_labels() -> None:
    claims, _ = _fixture()
    book = _book(claims)
    # outside the contract period: nothing ceded
    later = Section(
        "QS",
        "QUOTA_SHARE",
        cession_share=0.3,
        inception=date(2021, 1, 1),
        expiry=date(2022, 1, 1),
        currency="TRY",
    )
    assert apply_programme([later], book).ceded.height == 0
    # another line: nothing ceded
    other = Section("QS", "QUOTA_SHARE", cession_share=0.3, lines=frozenset({"MOTOR_OD"}), **YEAR)
    assert apply_programme([other], book).ceded.height == 0
    # risks attaching without policy start dates: out of scope and listed
    attaching = Section(
        "QS", "QUOTA_SHARE", cession_share=0.3, attachment_basis="RISKS_ATTACHING", **YEAR
    )
    no_start = ClaimBook(book.valuations, book.claims, None)
    app = apply_programme([attaching], no_start)
    assert app.ceded.height == 0 and app.out_of_scope.height == 12
    # event cover without any event code: per claim, labelled
    no_codes = ClaimBook(book.valuations, book.claims.drop("event_code"), book.policies)
    app = apply_programme([EVENT_XL], no_codes)
    assert EVENT_PER_CLAIM in app.sections[0].notes
    assert sum(_ceded(app, "CAT").values()) == pytest.approx(
        150 * 5 + (130 - 120) + (210 - 120) + (150 - 120)
    )
    # surplus without a sum insured: not applied to that claim, counted
    assert book.policies is not None
    partial = book.policies.with_columns(
        pl.when(pl.col("policy_id") == "12")
        .then(None)
        .otherwise(pl.col("sum_insured"))
        .alias("sum_insured")
    )
    app = apply_programme([SURPLUS], ClaimBook(book.valuations, book.claims, partial))
    assert "12" not in _ceded(app, "SP")
    assert any("1 claims without a usable sum insured" in n for n in app.sections[0].notes)


def test_treaties_without_their_terms_are_left_out() -> None:
    frame = pl.DataFrame(
        {
            "treaty_id": ["QS", "XL", "SP"],
            "treaty_type": ["QUOTA_SHARE", "EXCESS_OF_LOSS", "SURPLUS"],
            "inception_date": [date(2020, 1, 1)] * 3,
            "expiry_date": [date(2021, 1, 1)] * 3,
            "currency": ["TRY"] * 3,
            "line": ["PROPERTY", "PROPERTY", "PROPERTY"],
            "cession_share": [0.3, None, None],
            "retention": [None, None, 400.0],
            "limit": [None, 200.0, None],
            "number_of_lines": [None, None, 4.0],
        }
    )
    sections, excluded = sections_from_frame(frame)
    assert [s.treaty_id for s in sections] == ["SP", "QS"]  # inuring order
    assert [e.treaty_id for e in excluded] == ["XL"]
    assert "DV-RTY-05" in excluded[0].reason


# ------------------------------------------------------------------ properties

amounts = st.lists(st.integers(min_value=0, max_value=5000), min_size=1, max_size=6)


def _simple_book(gross: list[int], paid_share: float = 1.0) -> ClaimBook:
    ids = [f"{i:02d}" for i in range(len(gross))]
    return ClaimBook(
        valuations=pl.DataFrame(
            {
                "claim_id": ids,
                "valuation_date": [CUT] * len(ids),
                "paid": [g * paid_share for g in gross],
                "incurred": [float(g) for g in gross],
            }
        ),
        claims=pl.DataFrame(
            {
                "claim_id": ids,
                "occurrence_date": [date(2020, 3, 1)] * len(ids),
                "event_code": ["E1" if i % 2 else None for i in range(len(ids))],
                "policy_id": ids,
            }
        ),
        policies=pl.DataFrame(
            {
                "policy_id": ids,
                "start_date": [date(2020, 1, 1)] * len(ids),
                "sum_insured": [3000.0] * len(ids),
            }
        ),
    )


def _programme(retention: float) -> list[Section]:
    return [
        Section("SP", "SURPLUS", retention=1000, number_of_lines=1, **YEAR),
        Section("QS", "QUOTA_SHARE", cession_share=0.25, **YEAR),
        Section("XL", "EXCESS_OF_LOSS", retention=retention, limit=800, **YEAR),
        Section(
            "CAT", "EXCESS_OF_LOSS", loss_basis="EVENT", retention=retention, limit=500, **YEAR
        ),
    ]


@settings(max_examples=6, deadline=None)
@given(gross=amounts, retention=st.integers(min_value=0, max_value=2000), extra=st.integers(0, 500))
def test_properties_of_the_application(gross: list[int], retention: int, extra: int) -> None:
    book = _simple_book(gross, paid_share=0.6)
    app = apply_programme(_programme(retention), book)
    net = app.net
    for basis in ("paid", "incurred"):
        g = net[f"gross_{basis}"].to_numpy()
        c = net[f"ceded_{basis}"].to_numpy()
        assert (net[f"net_{basis}"].to_numpy() == g - c).all()  # net = gross - ceded exactly
        assert (c <= g + 1e-12).all() and (c >= -1e-12).all()
        by_claim = app.ceded.group_by("claim_id").agg(pl.col(f"ceded_{basis}").sum())
        assert by_claim[f"ceded_{basis}"].sum() == pytest.approx(c.sum(), abs=1e-9)
    # a higher retention of both layers: the programme cedes no more (a later stage may take
    # part of what an earlier one gives up, never more than all of it)
    higher = apply_programme(_programme(retention + extra), book)
    assert float(higher.net["ceded_incurred"].sum()) <= float(net["ceded_incurred"].sum()) + 1e-9
    empty = apply_programme([], book)
    assert (empty.net["net_incurred"] == empty.net["gross_incurred"]).all()


@settings(max_examples=6, deadline=None)
@given(gross=amounts, factor=st.integers(min_value=1, max_value=7))
def test_quota_share_is_linear(gross: list[int], factor: int) -> None:
    one = apply_programme([QUOTA], _simple_book(gross))
    many = apply_programme([QUOTA], _simple_book([g * factor for g in gross]))
    a, b = one.net["ceded_incurred"].to_numpy(), many.net["ceded_incurred"].to_numpy()
    assert b == pytest.approx(a * factor, rel=1e-12, abs=1e-12)


# ------------------------------------------------------------------ aggregate terms, index clause


def _folder():
    return load_reference("MT21-reinsurance-twelve-claims")["folder"]


def _layer_book() -> ClaimBook:
    rows = load_table(_folder() / "layers.csv")
    ids = [r["claim_id"] for r in rows]
    gross = [float(r["gross_loss"]) for r in rows]
    return ClaimBook(
        valuations=pl.DataFrame(
            {"claim_id": ids, "valuation_date": [CUT] * len(ids), "paid": gross, "incurred": gross}
        ),
        claims=pl.DataFrame(
            {
                "claim_id": ids,
                "occurrence_date": [date.fromisoformat(r["occurrence_date"]) for r in rows],
            }
        ),
    )


def test_reinstatements_and_aggregate_terms() -> None:
    _, values = _fixture()
    book = _layer_book()
    ids = book.claims["claim_id"].to_list()
    two = Section(
        "XL",
        "EXCESS_OF_LOSS",
        retention=50,
        limit=100,
        reinstatements=2,
        reinstatement_rate=1.0,
        **YEAR,
    )
    app = apply_programme([two], book, Options(deposit_premium={two.key: 30.0}))
    _check(values, "reinstatements_case_ceded", _ceded(app, "XL"), ids)
    result = app.sections[0]
    assert result.reinstatements_used == pytest.approx(
        values[("reinstatements_case", "reinstatements_used")]["value"]
    )
    assert result.reinstatement_premium == pytest.approx(
        values[("reinstatements_case", "reinstatement_premium")]["value"], rel=1e-12
    )
    assert result.use is not None and result.use.aggregate_exhausted
    crossed = Section(
        "XL",
        "EXCESS_OF_LOSS",
        retention=50,
        limit=100,
        aggregate_deductible=60,
        aggregate_limit=130,
        **YEAR,
    )
    app = apply_programme([crossed], book)
    _check(values, "aggregate_case_ceded", _ceded(app, "XL"), ids)
    assert app.sections[0].use is not None
    assert app.sections[0].use.aggregate_deductible_used == 60


def _index_book_and_options(clause: str) -> tuple[ClaimBook, Options]:
    rows = load_table(_folder() / "valuations.csv")
    index = load_table(_folder() / "index.csv")
    market = pl.DataFrame(
        {
            "series_id": ["CPI"] * len(index),
            "date": [date.fromisoformat(r["month"] + "-01") for r in index],
            "value": [float(r["value"]) for r in index],
            "kind": ["PRICE_INDEX"] * len(index),
        }
    )
    book = ClaimBook(
        valuations=pl.DataFrame(
            {
                "claim_id": [r["claim_id"] for r in rows],
                "valuation_date": [date.fromisoformat(r["valuation_date"]) for r in rows],
                "paid": [float(r["paid_to_date"]) for r in rows],
                "incurred": [float(r["paid_to_date"]) + float(r["case_reserve"]) for r in rows],
            }
        ),
        claims=pl.DataFrame(
            {
                "claim_id": ["I1", "I2"],
                "occurrence_date": [date(2020, 3, 15), date(2020, 2, 10)],
            }
        ),
    )
    return book, Options(index_clause=clause, price_index=price_indices(market))


@pytest.mark.parametrize("clause", [PAYMENT_BY_PAYMENT, OCCURRENCE_DATE])
def test_index_clause_by_hand(clause: str) -> None:
    _, values = _fixture()
    book, options = _index_book_and_options(clause)
    layer = Section("XL", "EXCESS_OF_LOSS", retention=100, limit=100, index_series="CPI", **YEAR)
    app = apply_programme([layer], book, options)
    for row in app.ceded.iter_rows(named=True):
        key = f"{row['claim_id']} {row['valuation_date'].isoformat()}"
        for basis in ("paid", "incurred"):
            expected = values[(f"{clause}_ceded_{basis}", key)]["value"]
            assert row[f"ceded_{basis}"] == pytest.approx(expected, rel=1e-12, abs=1e-12), (
                key,
                basis,
            )
    assert any(
        clause.replace("_", " ") in n or "occurrence date" in n for n in app.sections[0].notes
    )
    # a series missing from market: no indexation, named
    plain = apply_programme([layer], book, Options(index_clause=clause))
    assert any("DV-RTY-10" in n for n in plain.sections[0].notes)


@settings(max_examples=5, deadline=None)
@given(
    payments=st.lists(st.integers(min_value=-50, max_value=400), min_size=1, max_size=4),
    retention=st.integers(min_value=0, max_value=300),
    extra=st.integers(min_value=0, max_value=200),
)
def test_properties_hold_with_the_index_clause(
    payments: list[int], retention: int, extra: int
) -> None:
    days = [date(2020, 6, 30), date(2020, 9, 30), date(2020, 12, 31), date(2021, 3, 31)][
        : len(payments)
    ]
    paid = [max(0.0, float(sum(payments[: i + 1]))) for i in range(len(payments))]
    book = ClaimBook(
        valuations=pl.DataFrame(
            {
                "claim_id": ["A"] * len(paid),
                "valuation_date": days,
                "paid": paid,
                "incurred": [p + 50 for p in paid],
            }
        ),
        claims=pl.DataFrame({"claim_id": ["A"], "occurrence_date": [date(2020, 3, 15)]}),
    )
    for clause in (PAYMENT_BY_PAYMENT, OCCURRENCE_DATE):
        options = _index_book_and_options(clause)[1]
        net = {}
        for r in (retention, retention + extra):
            layer = Section(
                "XL", "EXCESS_OF_LOSS", retention=r, limit=150, index_series="CPI", **YEAR
            )
            app = apply_programme([layer], book, options)
            for basis in ("paid", "incurred"):
                g, c = app.net[f"gross_{basis}"].to_numpy(), app.net[f"ceded_{basis}"].to_numpy()
                assert (app.net[f"net_{basis}"].to_numpy() == g - c).all()
                assert (c <= g + 1e-9).all() and (c >= -1e-12).all()
            net[r] = float(app.net["ceded_incurred"].sum())
        assert net[retention + extra] <= net[retention] + 1e-9


def test_event_layer_with_the_index_clause_adds_its_claims() -> None:
    """Two claims of one event paid in the same months cede, together, what one claim with the
    summed payments cedes under the same indexed layer."""
    _, options = _index_book_and_options(PAYMENT_BY_PAYMENT)
    days = [date(2020, 6, 30), date(2020, 9, 30), date(2020, 12, 31)]
    a, b = [60.0, 100.0, 150.0], [40.0, 90.0, 95.0]

    def book(paid: dict[str, list[float]]) -> ClaimBook:
        ids = [c for c in paid for _ in days]
        return ClaimBook(
            valuations=pl.DataFrame(
                {
                    "claim_id": ids,
                    "valuation_date": days * len(paid),
                    "paid": [x for c in paid for x in paid[c]],
                    "incurred": [x + 20 for c in paid for x in paid[c]],
                }
            ),
            claims=pl.DataFrame(
                {
                    "claim_id": list(paid),
                    "occurrence_date": [date(2020, 3, 15)] * len(paid),
                    "event_code": ["E"] * len(paid),
                }
            ),
        )

    event = Section(
        "CAT",
        "EXCESS_OF_LOSS",
        loss_basis="EVENT",
        retention=150,
        limit=200,
        index_series="CPI",
        **YEAR,
    )
    risk = Section("XL", "EXCESS_OF_LOSS", retention=150, limit=200, index_series="CPI", **YEAR)
    pair = apply_programme([event], book({"A": a, "B": b}), options).net
    one = apply_programme(
        [risk], book({"S": [x + y for x, y in zip(a, b, strict=True)]}), options
    ).net
    together = (
        pair.group_by("valuation_date").agg(pl.col("ceded_paid").sum()).sort("valuation_date")
    )
    assert together["ceded_paid"].to_list() == pytest.approx(one["ceded_paid"].to_list(), rel=1e-12)
