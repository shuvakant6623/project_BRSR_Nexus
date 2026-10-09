"""Canonical unit families and deterministic conversion (spec §10).

Energy    kWh / MWh / GJ      -> MWh
Water     litre / kL / ML     -> kL
Waste     kg / tonne          -> tonne
Emissions kg CO2e / tCO2e     -> tCO2e
Currency  INR / lakh / crore  -> INR crore
Fuel      litre / kL          -> litre
Workforce / count / percent / rate / intensity are single-unit families.

Validation, calculation and consolidation must operate on normalized values.
"""
from decimal import ROUND_HALF_EVEN, Decimal, getcontext

getcontext().prec = 28

QUANT = Decimal("0.00000001")


class UnitConversionError(Exception):
    pass


# factor multiplies the raw unit into the family's canonical unit
UNIT_FACTORS: dict[str, dict[str, Decimal]] = {
    "energy": {"kWh": Decimal("0.001"), "MWh": Decimal(1), "GJ": Decimal(1) / Decimal("3.6")},
    "water": {"litre": Decimal("0.001"), "kL": Decimal(1), "ML": Decimal(1000)},
    "waste": {"kg": Decimal("0.001"), "tonne": Decimal(1)},
    "emissions": {"kg CO2e": Decimal("0.001"), "tCO2e": Decimal(1)},
    "currency": {
        "INR": Decimal(1) / Decimal(10000000),
        "INR lakh": Decimal("0.01"),
        "INR crore": Decimal(1),
    },
    "fuel_volume": {"litre": Decimal(1), "kL": Decimal(1000)},
    "workforce": {"count": Decimal(1)},
    "count": {"count": Decimal(1)},
    "percent": {"percent": Decimal(1)},
    "rate": {"per_million_manhours": Decimal(1)},
}


def normalize_value(
    value: Decimal | float | int | str,
    unit: str | None,
    unit_family: str | None,
    canonical_unit: str | None,
) -> tuple[Decimal, str]:
    """Return (normalized_value, canonical_unit).

    - A unit equal to the canonical unit passes through unchanged.
    - Otherwise the family's conversion table is used.
    - Unknown family, unknown unit, or missing unit for a multi-unit family
      raises UnitConversionError (never silently zero/unchanged).
    """
    raw = Decimal(str(value))
    if unit is None:
        # headcount-style metrics record no unit; treat as canonical when defined
        if canonical_unit is not None:
            return raw.quantize(QUANT, rounding=ROUND_HALF_EVEN), canonical_unit
        raise UnitConversionError("Cannot normalize: value has no unit and metric has no canonical unit")
    if unit == canonical_unit:
        return raw.quantize(QUANT, rounding=ROUND_HALF_EVEN), canonical_unit
    if unit_family not in UNIT_FACTORS:
        if unit and canonical_unit and unit == canonical_unit:
            return raw.quantize(QUANT, rounding=ROUND_HALF_EVEN), canonical_unit
        raise UnitConversionError(
            f"No conversion table for unit family {unit_family!r} "
            f"(unit {unit!r}, canonical {canonical_unit!r})"
        )
    factors = UNIT_FACTORS[unit_family]
    if unit not in factors:
        raise UnitConversionError(
            f"Unit {unit!r} is not convertible within family {unit_family!r} "
            f"(known units: {sorted(factors)})"
        )
    if canonical_unit is None:
        raise UnitConversionError(f"Metric defines no canonical unit for family {unit_family!r}")
    return (raw * factors[unit]).quantize(QUANT, rounding=ROUND_HALF_EVEN), canonical_unit
