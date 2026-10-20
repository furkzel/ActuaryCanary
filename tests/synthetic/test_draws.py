"""Seeded streams and distribution sampling."""

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from actuarycanary.synthetic.draws import Streams, draw, mean_of
from actuarycanary.synthetic.scenario import Dist


def test_a_stream_depends_only_on_the_seed_and_its_name():
    a = Streams(7).get("claims", "MOTOR_OD").random(5)
    b = Streams(7).get("claims", "MOTOR_OD").random(5)
    assert (a == b).all()
    assert not (a == Streams(8).get("claims", "MOTOR_OD").random(5)).all()
    assert not (a == Streams(7).get("claims", "MOTOR_TPL").random(5)).all()


def test_drawing_from_one_stream_does_not_move_another():
    streams = Streams(3)
    first = streams.get("a")
    first.random(1000)
    assert (streams.get("b").random(3) == Streams(3).get("b").random(3)).all()


def test_lognormal_has_the_given_median_and_mean():
    spec = Dist(dist="lognormal", median=1000, sigma=0.8)
    sample = draw(spec, np.random.default_rng(1), 200_000)
    assert np.median(sample) == pytest.approx(1000, rel=0.02)
    assert sample.mean() == pytest.approx(mean_of(spec), rel=0.03)


def test_gamma_has_the_given_mean_and_coefficient_of_variation():
    spec = Dist(dist="gamma", mean=500, cv=1.5)
    sample = draw(spec, np.random.default_rng(2), 200_000)
    assert sample.mean() == pytest.approx(500, rel=0.02)
    assert sample.std() / sample.mean() == pytest.approx(1.5, rel=0.03)


def test_poisson_count_respects_its_minimum():
    sample = draw(Dist(dist="poisson", mean=0.3, min=1), np.random.default_rng(3), 5000)
    assert sample.min() == 1


@given(st.floats(0.1, 1e6), st.integers(0, 50))
def test_a_fixed_value_is_returned_unchanged(value, n):
    assert (draw(Dist(dist="fixed", value=value), np.random.default_rng(0), n) == value).all()


def test_a_distribution_without_its_parameters_is_rejected():
    with pytest.raises(ValueError, match="needs sigma"):
        Dist(dist="lognormal", median=1)
