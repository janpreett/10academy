"""Account transaction history and inclusive UTC date filters."""

import sqlite3
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from app.cursors import InvalidCursor, TransactionCursor, decode_cursor, encode_cursor
from app.db import get_conn
from app.models import TransactionHistoryResponse, TransactionItem, TransactionType
from app.money import format_money, read_money
from app.timestamps import UTC_SORT_KEY

router = APIRouter()
DATE_PATTERN = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"


def parse_filter_date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise HTTPException(status_code=422, detail="invalid calendar date") from error


@router.get(
    "/accounts/{account_id}/transactions",
    response_model=TransactionHistoryResponse,
)
def get_transactions(
    account_id: str,
    from_date: str | None = Query(default=None, alias="from", pattern=DATE_PATTERN, max_length=10),
    to_date: str | None = Query(default=None, alias="to", pattern=DATE_PATTERN, max_length=10),
    transaction_type: TransactionType | None = Query(default=None, alias="type"),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None),
    connection: sqlite3.Connection = Depends(get_conn),
) -> TransactionHistoryResponse:
    start_date = parse_filter_date(from_date)
    end_date = parse_filter_date(to_date)
    if start_date is not None and end_date is not None and start_date > end_date:
        raise HTTPException(status_code=422, detail="from date must not be after to date")

    if connection.execute(
        "SELECT 1 FROM accounts WHERE id = ?", (account_id,)
    ).fetchone() is None:
        raise HTTPException(status_code=404, detail="account not found")

    secret = connection.execute("SELECT secret FROM cursor_signing_key WHERE id = 1").fetchone()[0]
    page_cursor = None
    if cursor is not None:
        try:
            page_cursor = decode_cursor(cursor, secret)
        except InvalidCursor as error:
            raise HTTPException(status_code=400, detail="invalid cursor") from error
        if (
            page_cursor.account_id != account_id
            or page_cursor.from_date != from_date
            or page_cursor.to_date != to_date
            or page_cursor.transaction_type != transaction_type
        ):
            raise HTTPException(status_code=400, detail="cursor does not match account or filters")
        snapshot_id = page_cursor.snapshot_id
    else:
        # Later inserts get larger automatic IDs, even if their dates are older.
        # Keep this watermark unchanged until the caller starts a new traversal.
        snapshot_id = connection.execute(
            "SELECT COALESCE(MAX(id), 0) FROM transactions WHERE account_id = ?",
            (account_id,),
        ).fetchone()[0]

    conditions = ["account_id = ?", "id <= ?"]
    parameters: list[str | int] = [account_id, snapshot_id]
    # The service stores ISO timestamps in UTC. An exclusive next-day bound
    # includes the whole final day and lets SQLite use the timestamp index.
    if start_date is not None:
        conditions.append("created_at >= ?")
        parameters.append(start_date.isoformat())
    if end_date is not None and end_date < date.max:
        conditions.append("created_at < ?")
        parameters.append((end_date + timedelta(days=1)).isoformat())
    if transaction_type is not None:
        conditions.append("type = ?")
        parameters.append(transaction_type)
    if page_cursor is not None:
        # The ID breaks timestamp ties so a boundary never drops tied records.
        conditions.append(f"(({UTC_SORT_KEY}), id) < (?, ?)")
        parameters.extend([page_cursor.last_created_at.removesuffix("+00:00"), page_cursor.last_id])
    parameters.append(limit + 1)

    # Only fixed SQL clauses are joined; all client values stay bound parameters.
    rows = connection.execute(
        f"SELECT id, type, amount, created_at, ({UTC_SORT_KEY}) AS sort_timestamp "
        "FROM transactions WHERE "
        + " AND ".join(conditions)
        + " ORDER BY sort_timestamp DESC, id DESC LIMIT ?",
        parameters,
    ).fetchall()
    page_rows = rows[:limit]
    next_cursor = None
    if len(rows) > limit:
        last_row = page_rows[-1]
        next_cursor = encode_cursor(
            TransactionCursor(
                account_id=account_id, from_date=from_date, to_date=to_date,
                transaction_type=transaction_type, snapshot_id=snapshot_id,
                last_id=last_row["id"], last_created_at=last_row["sort_timestamp"] + "+00:00",
            ),
            secret,
        )
    return TransactionHistoryResponse(
        items=[
            TransactionItem(
                id=row["id"], type=row["type"],
                amount=format_money(read_money(row["amount"])),
                created_at=row["created_at"],
            )
            for row in page_rows
        ],
        next_cursor=next_cursor,
    )
