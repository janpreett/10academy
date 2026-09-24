import sqlite3
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException

from app.db import get_conn, write_transaction
from app.models import TransferRequest, TransferResponse
from app.money import MAX_MONEY, format_money, read_money, read_transfer_balance

router = APIRouter()


@router.post("/transfers", status_code=201, response_model=TransferResponse)
def create_transfer(
    request: TransferRequest,
    connection: sqlite3.Connection = Depends(get_conn),
    idempotency_key: str | None = Header(default=None, min_length=1, max_length=200),
) -> TransferResponse:
    if request.from_account == request.to_account:
        raise HTTPException(status_code=422, detail="accounts must be different")
    if idempotency_key is not None and not idempotency_key.strip():
        raise HTTPException(status_code=422, detail="idempotency key must not be blank")

    with write_transaction(connection):
        if idempotency_key is not None:
            previous_request = connection.execute(
                "SELECT * FROM transfer_requests WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if previous_request is not None:
                if (
                    previous_request["from_account"] != request.from_account
                    or previous_request["to_account"] != request.to_account
                    or read_money(previous_request["amount"]) != request.amount
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="idempotency key already used for a different transfer",
                    )
                return TransferResponse(
                    transfer_id=previous_request["transfer_id"],
                    from_balance=previous_request["from_balance"],
                    to_balance=previous_request["to_balance"],
                )

        source_account = connection.execute(
            "SELECT balance FROM accounts WHERE id = ?", (request.from_account,)
        ).fetchone()
        destination_account = connection.execute(
            "SELECT balance FROM accounts WHERE id = ?", (request.to_account,)
        ).fetchone()
        if source_account is None or destination_account is None:
            raise HTTPException(status_code=404, detail="account not found")

        try:
            source_balance = read_transfer_balance(source_account["balance"])
            destination_balance = read_transfer_balance(destination_account["balance"])
        except ValueError as error:
            raise HTTPException(status_code=409, detail="unsupported account balance") from error
        if source_balance < request.amount:
            raise HTTPException(status_code=409, detail="insufficient funds")

        source_balance -= request.amount
        destination_balance += request.amount
        if destination_balance > MAX_MONEY:
            raise HTTPException(status_code=409, detail="destination balance limit exceeded")
        transfer_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

        # Bind decimal text for compatibility with the existing REAL schema.
        connection.execute(
            "UPDATE accounts SET balance = ? WHERE id = ?",
            (str(source_balance), request.from_account),
        )
        connection.execute(
            "UPDATE accounts SET balance = ? WHERE id = ?",
            (str(destination_balance), request.to_account),
        )
        connection.execute(
            """
            INSERT INTO transfers
                (id, from_account, to_account, amount, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                transfer_id, request.from_account, request.to_account,
                str(request.amount), created_at,
            ),
        )
        connection.executemany(
            """
            INSERT INTO transactions
                (account_id, type, amount, created_at, transfer_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (request.from_account, "transfer_out", str(request.amount),
                 created_at, transfer_id),
                (request.to_account, "transfer_in", str(request.amount),
                 created_at, transfer_id),
            ],
        )
        response = TransferResponse(
            transfer_id=transfer_id,
            from_balance=format_money(source_balance),
            to_balance=format_money(destination_balance),
        )
        if idempotency_key is not None:
            # Store the original response, not a view of the current balances.
            connection.execute(
                """
                INSERT INTO transfer_requests
                    (idempotency_key, from_account, to_account, amount,
                     transfer_id, from_balance, to_balance)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    idempotency_key, request.from_account, request.to_account,
                    str(request.amount), transfer_id,
                    response.from_balance, response.to_balance,
                ),
            )
        return response
