"""Unit tests for the safe formula evaluator (spec §12, §38)."""
from decimal import Decimal

import pytest

from app.calculation.evaluator import CalculationError, evaluate


def resolve(name: str) -> Decimal:
    table = {
        "A": Decimal("10"),
        "B": Decimal("4"),
        "C-P6-GRID-RENEWABLE-MWH": Decimal("30"),
        "DIESEL_EF_KG_PER_LITRE": Decimal("2.68"),
    }
    if name not in table:
        raise CalculationError(f"Unknown identifier {name!r}")
    return table[name]


def test_addition_and_precedence():
    assert evaluate("2 + 3 * 4", resolve) == Decimal("14.00000000")


def test_parentheses():
    assert evaluate("(2 + 3) * 4", resolve) == Decimal("20.00000000")


def test_division():
    assert evaluate("10 / 4", resolve) == Decimal("2.50000000")


def test_unary_minus():
    assert evaluate("-A + 5", resolve) == Decimal("-5.00000000")


def test_double_minus_is_valid_arithmetic():
    assert evaluate("A -- 2", resolve) == Decimal("12.00000000")


def test_metric_codes_with_hyphens():
    assert evaluate("C-P6-GRID-RENEWABLE-MWH * 2", resolve) == Decimal("60.00000000")


def test_constants_and_inputs_mixed():
    assert evaluate("A * DIESEL_EF_KG_PER_LITRE / 1000", resolve) == Decimal("0.02680000")


def test_division_by_zero_raises():
    with pytest.raises(CalculationError, match="Division by zero"):
        evaluate("10 / 0", resolve)


def test_division_by_zero_expression_raises():
    with pytest.raises(CalculationError, match="Division by zero"):
        evaluate("10 / (A - A)", resolve)


def test_unknown_identifier_raises():
    with pytest.raises(CalculationError, match="Unknown identifier"):
        evaluate("A + NOPE", resolve)


def test_injection_attempts_rejected():
    for payload in [
        "().__import__('os').system('ls')",
        "__import__('os')",
        "A; DROP TABLE users",
        "open('/etc/passwd')",
        "eval('1')",
        "A '",
    ]:
        with pytest.raises(CalculationError):
            evaluate(payload, resolve)


def test_unbalanced_parentheses_raises():
    with pytest.raises(CalculationError):
        evaluate("(A + 2", resolve)


def test_trailing_garbage_raises():
    with pytest.raises(CalculationError):
        evaluate("A 2 2", resolve)


def test_empty_formula_raises():
    with pytest.raises(CalculationError):
        evaluate("", resolve)


def test_determinism():
    expr = "A * DIESEL_EF_KG_PER_LITRE / 1000 + C-P6-GRID-RENEWABLE-MWH"
    assert evaluate(expr, resolve) == evaluate(expr, resolve) == Decimal("30.02680000")
