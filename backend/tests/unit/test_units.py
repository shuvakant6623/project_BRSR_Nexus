"""Unit tests for deterministic unit conversion (spec §10, §38)."""
from decimal import Decimal

import pytest

from app.normalization.units import UnitConversionError, normalize_value


def test_kwh_to_mwh():
    value, unit = normalize_value(170000, "kWh", "energy", "MWh")
    assert value == Decimal("170.00000000")
    assert unit == "MWh"


def test_gj_to_mwh():
    value, _ = normalize_value(3.6, "GJ", "energy", "MWh")
    assert value == Decimal("1.00000000")


def test_litre_to_kl():
    value, _ = normalize_value(5000000, "litre", "water", "kL")
    assert value == Decimal("5000.00000000")


def test_ml_to_kl():
    value, _ = normalize_value(2.5, "ML", "water", "kL")
    assert value == Decimal("2500.00000000")


def test_kg_to_tonne():
    value, _ = normalize_value(1500, "kg", "waste", "tonne")
    assert value == Decimal("1.50000000")


def test_kg_co2e_to_tco2e():
    value, unit = normalize_value(2680, "kg CO2e", "emissions", "tCO2e")
    assert value == Decimal("2.68000000")
    assert unit == "tCO2e"


def test_inr_and_lakh_to_crore():
    assert normalize_value(10000000, "INR", "currency", "INR crore")[0] == Decimal("1.00000000")
    assert normalize_value(250, "INR lakh", "currency", "INR crore")[0] == Decimal("2.50000000")


def test_canonical_pass_through():
    value, unit = normalize_value(42, "MWh", "energy", "MWh")
    assert value == Decimal("42.00000000")
    assert unit == "MWh"


def test_single_unit_family():
    value, unit = normalize_value(210, "count", "workforce", "count")
    assert value == Decimal("210.00000000") and unit == "count"


def test_unknown_unit_raises():
    with pytest.raises(UnitConversionError):
        normalize_value(1, "bogus_unit", "energy", "MWh")


def test_wrong_family_unit_raises():
    with pytest.raises(UnitConversionError):
        normalize_value(1, "kL", "energy", "MWh")


def test_missing_unit_and_missing_canonical_raises():
    with pytest.raises(UnitConversionError):
        normalize_value(1, None, "energy", None)


def test_missing_unit_for_multi_unit_family_is_canonical():
    # headcount-style metrics record no unit; with a canonical unit defined the
    # value is treated as already canonical
    value, unit = normalize_value(100, None, "energy", "MWh")
    assert value == Decimal("100.00000000") and unit == "MWh"


def test_missing_unit_for_single_unit_family_ok():
    value, unit = normalize_value(7, None, "percent", "percent")
    assert value == Decimal("7.00000000") and unit == "percent"
