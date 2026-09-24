"""Decimal conversion at the boundary of the seed's SQLite REAL columns."""

from decimal import Decimal, InvalidOperation


# Stay below 15 significant digits while retaining the seed's REAL columns.
MAX_MONEY = Decimal("999999999999.99")
CENT = Decimal("0.01")


def read_money(value: str | float | int) -> Decimal:
    # Converting through text avoids importing the float's binary expansion.
    # REAL storage still has a finite precision; this is not a storage migration.
    return Decimal(str(value))


def format_money(value: Decimal) -> str:
    return f"{value:.2f}"


def read_transfer_balance(value: str | float | int) -> Decimal:
    """Reject inconsistent stored money instead of silently rounding it."""
    try:
        balance = read_money(value)
        if (
            not balance.is_finite()
            or not Decimal("0") <= balance <= MAX_MONEY
            or balance != balance.quantize(CENT)
            or Decimal(str(float(balance))) != balance
        ):
            raise ValueError("unsupported account balance")
    except InvalidOperation as error:
        raise ValueError("unsupported account balance") from error
    return balance
