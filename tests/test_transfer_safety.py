import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from decimal import Decimal
from threading import Barrier

import pytest
from app.db import connect, get_conn
from app.main import app


def transfer(client, amount=100, source="ACC-1001", destination="ACC-1002", key=None):
    return client.post(
        "/transfers",
        json={"from_account": source, "to_account": destination, "amount": amount},
        headers={"Idempotency-Key": key} if key is not None else {},
    )


def ledger_state(db_path):
    with closing(connect(db_path)) as connection:
        return {
            "balances": [tuple(row) for row in connection.execute(
                "SELECT id, balance FROM accounts ORDER BY id"
            )],
            "transfers": [tuple(row) for row in connection.execute(
                "SELECT * FROM transfers ORDER BY id"
            )],
            "transactions": [tuple(row) for row in connection.execute(
                "SELECT * FROM transactions ORDER BY id"
            )],
            "requests": [tuple(row) for row in connection.execute(
                "SELECT * FROM transfer_requests ORDER BY idempotency_key"
            )],
        }


@pytest.mark.parametrize("amount", [
    0, -1, 0.001, "1.001", "NaN", "Infinity", "-Infinity", True,
    "1000000000000.00", "1e1000", "1e-1000",
])
def test_invalid_amount_changes_nothing(client, db_path, amount):
    before = ledger_state(db_path)
    assert transfer(client, amount, key="invalid-amount").status_code == 422
    assert ledger_state(db_path) == before


@pytest.mark.parametrize("amount_literal", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_nonfinite_json_number_is_a_validation_error(client, db_path, amount_literal):
    before = ledger_state(db_path)
    response = client.post(
        "/transfers",
        content='{"from_account":"ACC-1001","to_account":"ACC-1002","amount":'
        + amount_literal + '}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert ledger_state(db_path) == before


def test_same_account_transfer_cannot_create_money(client, db_path):
    before = ledger_state(db_path)
    assert transfer(client, destination="ACC-1001").status_code == 422
    assert ledger_state(db_path) == before


@pytest.mark.parametrize("key", ["", " ", "x" * 201])
def test_invalid_retry_key_changes_nothing(client, db_path, key):
    before = ledger_state(db_path)
    assert transfer(client, key=key).status_code == 422
    assert ledger_state(db_path) == before


@pytest.mark.parametrize("balance", [
    "1000000000000", "0.001", "-1", "NaN", "Infinity", "invalid", float("inf")
])
def test_invalid_stored_balance_is_not_used(client, db_path, balance):
    with closing(connect(db_path)) as connection:
        connection.execute("UPDATE accounts SET balance = ? WHERE id = 'ACC-1002'", (balance,))
        connection.commit()
    before = ledger_state(db_path)
    assert transfer(client).status_code == 409
    assert ledger_state(db_path) == before


def test_destination_balance_limit_changes_nothing(client, db_path):
    with closing(connect(db_path)) as connection:
        connection.execute("UPDATE accounts SET balance = 999999999999.99 WHERE id = 'ACC-1002'")
        connection.commit()
    before = ledger_state(db_path)
    assert transfer(client, 0.01).status_code == 409
    assert ledger_state(db_path) == before


@pytest.mark.parametrize("cents", [1, 7, 29, 49, 99])
def test_cent_transfer_at_supported_balance_limit_is_exact(client, db_path, cents):
    with closing(connect(db_path)) as connection:
        connection.execute("UPDATE accounts SET balance = 999999999999.99 WHERE id = 'ACC-1001'")
        connection.commit()
    amount = Decimal(cents) / 100
    expected_source = Decimal("999999999999.99") - amount
    expected_destination = Decimal("500.00") + amount
    response = transfer(client, str(amount))
    assert response.status_code == 201
    assert response.json()["from_balance"] == str(expected_source)
    assert response.json()["to_balance"] == str(expected_destination)
    balances = [Decimal(str(balance)) for _, balance in ledger_state(db_path)["balances"]]
    assert balances == [expected_source, expected_destination]


@pytest.mark.parametrize("failure_stage", ["credit", "transfer", "second_entry"])
def test_failure_at_each_write_stage_rolls_back(client, db_path, failure_stage):
    # Only fixed test-owned SQL fragments are used in this trigger definition.
    triggers = {
        "credit": "BEFORE UPDATE ON accounts WHEN NEW.id = 'ACC-1002'",
        "transfer": "BEFORE INSERT ON transfers",
        "second_entry": "BEFORE INSERT ON transactions WHEN NEW.type = 'transfer_in'",
    }
    with closing(connect(db_path)) as connection:
        connection.execute(
            f"CREATE TRIGGER fail_write {triggers[failure_stage]} "
            "BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
        )
        connection.commit()
    before = ledger_state(db_path)
    with pytest.raises(sqlite3.IntegrityError, match="injected failure"):
        transfer(client, key="retry-after-failure")
    assert ledger_state(db_path) == before
    with closing(connect(db_path)) as connection:
        connection.execute("DROP TRIGGER fail_write")
        connection.commit()
    assert transfer(client, key="retry-after-failure").status_code == 201


@pytest.mark.parametrize("same_key", [False, True])
def test_concurrent_requests_conserve_money(client, db_path, same_key):
    start = Barrier(2)

    def make_request():
        start.wait(timeout=10)
        return transfer(client, 750, key="shared-key" if same_key else None)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(make_request) for _ in range(2)]
        responses = [future.result(timeout=15) for future in futures]

    assert sorted(response.status_code for response in responses) == (
        [201, 201] if same_key else [201, 409]
    )
    if same_key:
        assert responses[0].json() == responses[1].json()
    state = ledger_state(db_path)
    assert state["balances"] == [("ACC-1001", 250), ("ACC-1002", 1250)]
    assert len(state["transfers"]) == 1
    assert len(state["transactions"]) == 2


@pytest.mark.parametrize("lock_stage", ["begin", "commit"])
def test_busy_database_returns_retryable_error(client, db_path, lock_stage):
    previous_dependency = app.dependency_overrides[get_conn]

    def impatient_connection():
        with closing(connect(db_path)) as connection:
            connection.execute("PRAGMA busy_timeout = 1")
            yield connection

    before = ledger_state(db_path)
    app.dependency_overrides[get_conn] = impatient_connection
    try:
        with closing(connect(db_path)) as lock:
            if lock_stage == "begin":
                lock.execute("BEGIN IMMEDIATE")
            else:
                # A reader permits writes in rollback-journal mode but blocks commit.
                lock.execute("BEGIN")
                lock.execute("SELECT * FROM accounts").fetchall()
            response = transfer(client, key="busy-retry")
            lock.rollback()
        assert response.status_code == 503
        assert response.headers["Retry-After"] == "1"
        assert ledger_state(db_path) == before
        assert transfer(client, key="busy-retry").status_code == 201
    finally:
        app.dependency_overrides[get_conn] = previous_dependency


def test_declined_transfer_does_not_consume_retry_key(client, db_path):
    before = ledger_state(db_path)
    assert transfer(client, 1001, key="declined").status_code == 409
    assert ledger_state(db_path) == before
    assert transfer(client, 100, key="declined").status_code == 201


def test_entire_balance_can_be_transferred(client):
    response = transfer(client, 1000)
    assert response.status_code == 201
    assert response.json()["from_balance"] == "0.00"
    assert response.json()["to_balance"] == "1500.00"


def test_both_ledger_entries_match_transfer(client, db_path):
    response = transfer(client, 12.34)
    assert response.status_code == 201
    with closing(connect(db_path)) as connection:
        entries = connection.execute(
            "SELECT account_id, type, amount, transfer_id FROM transactions ORDER BY id"
        ).fetchall()
    assert [tuple(entry) for entry in entries] == [
        ("ACC-1001", "transfer_out", 12.34, response.json()["transfer_id"]),
        ("ACC-1002", "transfer_in", 12.34, response.json()["transfer_id"]),
    ]
