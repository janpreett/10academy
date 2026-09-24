"""Check history filters, response fields, and which account each record belongs to."""

from contextlib import closing

import pytest

from app.db import connect


@pytest.fixture
def transaction_ids(db_path):
    """Create records around date boundaries, plus one belonging to another account."""
    records = [
        ("ACC-1001", "deposit", 10, "2026-08-13T23:59:59+00:00"),
        ("ACC-1001", "withdrawal", 12.34, "2026-08-14T00:00:00+00:00"),
        ("ACC-1001", "transfer_in", 20, "2026-08-14T12:00:00+00:00"),
        ("ACC-1001", "transfer_out", 30, "2026-08-14T12:00:00+00:00"),
        ("ACC-1001", "deposit", 0.01, "2026-08-14T23:59:59.999999+00:00"),
        ("ACC-1001", "deposit", 40, "2026-08-15T00:00:00+00:00"),
        ("ACC-1002", "deposit", 999, "2026-08-16T00:00:00+00:00"),
    ]
    with closing(connect(db_path)) as connection:
        ids = [
            connection.execute(
                "INSERT INTO transactions (account_id, type, amount, created_at) "
                "VALUES (?, ?, ?, ?)", record,
            ).lastrowid
            for record in records
        ]
        connection.commit()
    return ids


def test_history_shape_order_and_account_isolation(client, transaction_ids):
    """Return only this account's records, newest first, with the required fields."""
    response = client.get("/accounts/ACC-1001/transactions")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items", "next_cursor"}
    assert body["next_cursor"] is None
    assert [item["id"] for item in body["items"]] == list(reversed(transaction_ids[:6]))
    assert body["items"][0] == {
        "id": transaction_ids[5], "type": "deposit", "amount": "40.00",
        "created_at": "2026-08-15T00:00:00+00:00",
    }
    assert body["items"][1]["amount"] == "0.01"
    assert all(set(item) == {"id", "type", "amount", "created_at"} for item in body["items"])


@pytest.mark.parametrize("filters, indexes", [
    ({"from": "2026-08-14"}, [5, 4, 3, 2, 1]),
    ({"to": "2026-08-14"}, [4, 3, 2, 1, 0]),
    ({"from": "2026-08-14", "to": "2026-08-14"}, [4, 3, 2, 1]),
    ({"from": "2026-08-14", "to": "2026-08-14", "type": "deposit"}, [4]),
    ({"from": "2026-09-01"}, []),
    ({"to": "2026-08-01"}, []),
    ({"from": "0001-01-01", "to": "9999-12-31"}, [5, 4, 3, 2, 1, 0]),
])
def test_inclusive_date_filters(client, transaction_ids, filters, indexes):
    """Include both chosen dates, even a record at the very end of the final day."""
    response = client.get("/accounts/ACC-1001/transactions", params=filters)
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [transaction_ids[i] for i in indexes]


@pytest.mark.parametrize("transaction_type, indexes", [
    ("deposit", [5, 4, 0]), ("withdrawal", [1]),
    ("transfer_in", [2]), ("transfer_out", [3]),
])
def test_type_filter(client, transaction_ids, transaction_type, indexes):
    """Each of the four allowed types should return only matching records."""
    response = client.get("/accounts/ACC-1001/transactions", params={"type": transaction_type})
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [transaction_ids[i] for i in indexes]


@pytest.mark.parametrize("parameter", ["from", "to"])
@pytest.mark.parametrize("value", [
    "", "not-a-date", "2026-02-30", "2026-8-14", "20260814",
    "2026-08-14T00:00:00Z", "1723593600", "2026-13-01", "0000-01-01",
])
def test_invalid_dates(client, parameter, value):
    """Reject impossible dates and inputs that are not written as YYYY-MM-DD."""
    response = client.get("/accounts/ACC-1001/transactions", params={parameter: value})
    assert response.status_code == 422


@pytest.mark.parametrize("value", ["", "DEPOSIT", "payment", "deposit' OR 1=1 --"])
def test_invalid_types(client, value):
    """Reject unknown types, including text that tries to act as SQL."""
    assert client.get("/accounts/ACC-1001/transactions", params={"type": value}).status_code == 422


def test_reversed_date_range(client):
    """The start date cannot come after the end date."""
    response = client.get(
        "/accounts/ACC-1001/transactions", params={"from": "2026-08-15", "to": "2026-08-14"}
    )
    assert response.status_code == 422


def test_empty_history(client):
    """An existing account with no transactions returns an empty final page."""
    response = client.get("/accounts/ACC-1001/transactions")
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}


def test_unknown_account(client):
    """Return 404 when the requested account does not exist."""
    assert client.get("/accounts/ACC-9999/transactions").status_code == 404


def test_account_id_is_not_sql(client, transaction_ids):
    """Treat SQL-like account IDs as values, not as part of the database query."""
    assert client.get("/accounts/ACC-1001' OR '1'='1/transactions").status_code == 404


def test_new_transfer_appears_in_both_accounts(client):
    """A successful transfer should appear in the sender's and receiver's histories."""
    response = client.post(
        "/transfers",
        json={"from_account": "ACC-1001", "to_account": "ACC-1002", "amount": 12.34},
    )
    assert response.status_code == 201
    outgoing = client.get("/accounts/ACC-1001/transactions").json()["items"]
    incoming = client.get("/accounts/ACC-1002/transactions").json()["items"]
    assert len(outgoing) == len(incoming) == 1
    assert outgoing[0]["type"] == "transfer_out"
    assert incoming[0]["type"] == "transfer_in"
    assert outgoing[0]["amount"] == incoming[0]["amount"] == "12.34"
