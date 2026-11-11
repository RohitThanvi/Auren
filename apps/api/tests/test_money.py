from typing import cast

import pytest

from auren_api.domain.money import Currency, Money


def inr(amount_minor: int) -> Money:
    return Money(amount_minor, Currency.INR)


def test_addition_and_subtraction_use_integer_minor_units() -> None:
    assert inr(1050) + inr(250) == inr(1300)
    assert inr(1050) - inr(250) == inr(800)


def test_currency_mismatch_is_rejected() -> None:
    other = Money(100, cast(Currency, "USD"))
    with pytest.raises(ValueError, match="currency mismatch"):
        _ = inr(100) + other
    with pytest.raises(ValueError, match="currency mismatch"):
        _ = inr(100) - other


@pytest.mark.parametrize(
    ("amount", "basis_points", "expected"),
    [
        (10_000, 1_000, 1_000),  # 10% of INR 100.00
        (999, 1_000, 100),  # 99.9 paise rounds up
        (994, 1_000, 99),  # 99.4 paise rounds down
        (995, 1_000, 100),  # exact half rounds up
        (0, 1_000, 0),
        (12_345, 0, 0),
        (12_345, 10_000, 12_345),
    ],
)
def test_basis_points_round_half_up(amount: int, basis_points: int, expected: int) -> None:
    assert inr(amount).apply_basis_points(basis_points) == inr(expected)


def test_basis_points_reject_negative_operands() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        inr(-1).apply_basis_points(100)
    with pytest.raises(ValueError, match="non-negative"):
        inr(1).apply_basis_points(-100)
