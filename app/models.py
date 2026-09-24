from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.money import MAX_MONEY


class TransferRequest(BaseModel):
    from_account: str
    to_account: str
    amount: Decimal = Field(
        gt=0, le=MAX_MONEY, max_digits=14, decimal_places=2, allow_inf_nan=False
    )


class TransferResponse(BaseModel):
    transfer_id: str
    from_balance: str
    to_balance: str


TransactionType = Literal["deposit", "withdrawal", "transfer_in", "transfer_out"]


class TransactionItem(BaseModel):
    id: int
    type: TransactionType
    amount: str
    created_at: str


class TransactionHistoryResponse(BaseModel):
    items: list[TransactionItem]
    next_cursor: str | None
