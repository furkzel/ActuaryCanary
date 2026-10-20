import pytest

from tests.benchmarks.load import benchmark_names, load_benchmark, load_hand

BENCHMARK_KEYS = {
    "name", "status", "checked_by_owner", "published_figures", "source", "origins", "ages",
    "ldf", "tail_factor", "cdf", "latest", "ultimate", "ibnr", "mack_std_err", "total",
}  # fmt: skip
METHOD_KEYS = {"ldf", "cdf", "chain_ladder", "bornhuetter_ferguson", "cape_cod"}


def test_benchmarks_found():
    assert {"raa", "genins"} <= set(benchmark_names())


@pytest.mark.parametrize("name", ["raa", "genins"])
def test_benchmark_has_required_keys(name):
    data = load_benchmark(name)
    exp = data["expected"]
    assert set(exp) >= BENCHMARK_KEYS
    assert exp["status"] == "reference_implementation"
    assert {"package", "version", "calls"} <= set(exp["source"])
    assert {"ultimate", "ibnr", "mack_std_err", "latest"} <= set(exp["total"])
    n = len(exp["origins"])
    assert data["triangle"]["origins"] == exp["origins"]
    assert data["triangle"]["ages"] == exp["ages"]
    assert len(exp["ldf"]) == n - 1
    for key in ("cdf", "latest", "ultimate", "ibnr", "mack_std_err"):
        assert len(exp[key]) == n


@pytest.mark.parametrize("name", ["raa", "genins"])
def test_benchmark_is_internally_consistent(name):
    """Recompute volume-weighted chain ladder from the triangle file alone."""
    data = load_benchmark(name)
    values, exp = data["triangle"]["values"], data["expected"]
    n = len(values)
    ldf = []
    for j in range(n - 1):
        rows = [r for r in values if r[j + 1] is not None]
        ldf.append(sum(r[j + 1] for r in rows) / sum(r[j] for r in rows))
    assert ldf == pytest.approx(exp["ldf"], rel=1e-9)
    for i, row in enumerate(values):
        last = max(j for j, v in enumerate(row) if v is not None)
        cdf = 1.0
        for f in ldf[last:]:
            cdf *= f
        assert row[last] * cdf == pytest.approx(exp["ultimate"][i], rel=1e-9)
    assert sum(exp["ibnr"]) == pytest.approx(exp["total"]["ibnr"], rel=1e-9)


def test_hand_fixture_has_required_keys():
    data = load_hand()
    exp = data["expected"]
    assert {"status", "checked_by_owner", "origins", "ages", "earned_premium"} <= set(exp)
    assert exp["status"] == "hand_computed"
    for basis in ("paid", "incurred"):
        assert set(exp[basis]) >= METHOD_KEYS
        assert len(exp[basis]["ldf"]) == 3
        for method in ("chain_ladder", "bornhuetter_ferguson", "cape_cod"):
            ultimate = exp[basis][method]["ultimate"]
            assert len(ultimate) == 4
            assert all(item["derivation"] and "value" in item for item in ultimate)
    assert data["paid"]["origins"] == exp["origins"]
    assert [data["premium"][o] for o in exp["origins"]] == exp["earned_premium"]


def test_hand_incurred_not_below_paid():
    data = load_hand()
    for p_row, i_row in zip(data["paid"]["values"], data["incurred"]["values"], strict=True):
        assert all(i >= p for p, i in zip(p_row, i_row, strict=True) if p is not None)
