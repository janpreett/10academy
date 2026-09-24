"""Regression coverage for precision and persistent retry handling."""

import sqlite3
from contextlib import closing
from decimal import Decimal

import pytest

from app.db import connect


def submit_transfer(client, amount, key=None, source="ACC-1001", destination="ACC-1002"):
    headers = {"Idempotency-Key": key} if key is not None else {}
    return client.post(
        "/transfers",
        json={"from_account": source, "to_account": destination, "amount": amount},
        headers=headers,
    )


def test_transfer_response_uses_two_decimal_places(client):
    response = submit_transfer(client, 250)

    assert response.status_code == 201
    assert set(response.json()) == {"transfer_id", "from_balance", "to_balance"}
    assert response.json()["from_balance"] == "750.00"
    assert response.json()["to_balance"] == "750.00"


def test_repeated_small_transfers_preserve_stored_balances(client, db_path):
    for _ in range(10):
        assert submit_transfer(client, 0.10).status_code == 201

    # Check persisted values so formatting cannot hide accumulating errors.
    with closing(connect(db_path)) as connection:
        balances = [
            Decimal(str(row["balance"]))
            for row in connection.execute("SELECT balance FROM accounts ORDER BY id")
        ]
    assert balances == [Decimal("999.00"), Decimal("501.00")]
    assert sum(balances) == Decimal("1500.00")


def test_retry_returns_original_response_after_other_transfers(client, db_path):
    original = submit_transfer(client, 100, key="original-transfer")
    assert original.status_code == 201
    assert submit_transfer(client, 50).status_code == 201

    # Each HTTP request uses a fresh connection: replay must live in SQLite.
    replay = submit_transfer(client, 100.0, key="original-transfer")
    assert replay.status_code == 201
    assert replay.json() == original.json()
    assert client.get("/accounts/ACC-1001").json()["balance"] == "850.00"
    assert client.get("/accounts/ACC-1002").json()["balance"] == "650.00"
    with closing(connect(db_path)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM transfers").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 4
        assert connection.execute("SELECT COUNT(*) FROM transfer_requests").fetchone()[0] == 1


@pytest.mark.parametrize(
    "amount, source, destination",
    [(101, "ACC-1001", "ACC-1002"), (100, "ACC-1002", "ACC-1001")],
)
def test_retry_key_cannot_be_reused_for_different_transfer(
    client, db_path, amount, source, destination
):
    original = submit_transfer(client, 100, key="used-key")
    assert original.status_code == 201

    response = submit_transfer(client, amount, "used-key", source, destination)

    assert response.status_code == 409
    assert client.get("/accounts/ACC-1001").json()["balance"] == "900.00"
    assert client.get("/accounts/ACC-1002").json()["balance"] == "600.00"
    with closing(connect(db_path)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM transfers").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 2
    assert submit_transfer(client, 100, key="used-key").json() == original.json()


def test_transfers_without_key_are_independent(client, db_path):
    first = submit_transfer(client, 100)
    second = submit_transfer(client, 100)

    assert first.status_code == second.status_code == 201
    assert first.json()["transfer_id"] != second.json()["transfer_id"]
    assert client.get("/accounts/ACC-1001").json()["balance"] == "800.00"
    with closing(connect(db_path)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM transfer_requests").fetchone()[0] == 0


def test_failed_idempotency_record_rolls_back_transfer(client, db_path):
    with closing(connect(db_path)) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_retry_record
            BEFORE INSERT ON transfer_requests
            BEGIN
                SELECT RAISE(ABORT, 'simulated write failure');
            END
            """
        )
        connection.commit()

    with pytest.raises(sqlite3.IntegrityError, match="simulated write failure"):
        submit_transfer(client, 100, key="failed-write")

    assert client.get("/accounts/ACC-1001").json()["balance"] == "1000.00"
    assert client.get("/accounts/ACC-1002").json()["balance"] == "500.00"
    with closing(connect(db_path)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM transfers").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM transfer_requests").fetchone()[0] == 0
        connection.execute("DROP TRIGGER reject_retry_record")
        connection.commit()

    assert submit_transfer(client, 100, key="failed-write").status_code == 201
