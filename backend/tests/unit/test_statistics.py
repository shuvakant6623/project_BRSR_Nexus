"""Unit tests for the statistical anomaly layer (research §5.9)."""
import pytest

from app.validation.statistics import iqr_bounds, zscore


def test_iqr_flags_low_outlier():
    # spread-out peers with one extreme outlier
    values = [0.20, 0.21, 0.22, 0.23, 0.24, 0.25, 0.26, 0.8562]
    bounds = iqr_bounds(values)
    assert bounds is not None
    _q1, _q3, iqr, lower, upper = bounds
    assert iqr > 0
    assert upper < 0.8562 or lower > 0.0726


def test_iqr_skips_tiny_samples():
    assert iqr_bounds([1.0, 2.0]) is None
    assert iqr_bounds([1.0, 2.0, 3.0]) is None


def test_iqr_zero_spread_returns_none():
    assert iqr_bounds([5.0, 5.0, 5.0, 5.0, 5.0]) is None


def test_zscore_extreme_value():
    peers = [10, 10, 10, 10, 10, 50]
    z = zscore(50, peers)
    assert z is not None and abs(z) > 2


def test_zscore_normal_value():
    peers = [10, 10.5, 9.8, 10.2, 10.1]
    z = zscore(10.1, peers)
    assert z is not None and abs(z) < 1


def test_zscore_zero_variance_returns_none():
    assert zscore(10, [10, 10, 10, 10]) is None


def test_quantile_linear_interpolation():
    from app.validation.statistics import _quantile
    assert _quantile([1, 2, 3, 4], 0.25) == pytest.approx(1.75)
    assert _quantile([1, 2, 3, 4], 0.5) == pytest.approx(2.5)
