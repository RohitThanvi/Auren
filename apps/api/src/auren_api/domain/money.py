"""Money as integer minor units. Floating point is never used for monetary values."""

from dataclasses import dataclass
from enum import StrEnum

BASIS_POINTS_PER_UNIT = 10_000


class Currency(StrEnum):
    INR = "INR"


@dataclass(frozen=True, slots=True)
class Money:
    """An amount in the smallest currency unit (paise for INR)."""

    amount_minor: int
    currency: Currency

    def __add__(self, other: "Money") -> "Money":
        self._require_same_currency(other)
        return Money(self.amount_minor + other.amount_minor, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._require_same_currency(other)
        return Money(self.amount_minor - other.amount_minor, self.currency)

    def apply_basis_points(self, basis_points: int) -> "Money":
        """Return ``basis_points`` / 10,000 of this amount, rounded half up (non-negative only)."""
        if self.amount_minor < 0 or basis_points < 0:
            raise ValueError("apply_basis_points requires non-negative operands")
        numerator = self.amount_minor * basis_points
        rounded = (numerator * 2 + BASIS_POINTS_PER_UNIT) // (BASIS_POINTS_PER_UNIT * 2)
        return Money(rounded, self.currency)

    def _require_same_currency(self, other: "Money") -> None:
        if self.currency is not other.currency:
            raise ValueError(f"currency mismatch: {self.currency} vs {other.currency}")
