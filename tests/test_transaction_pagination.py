import base64
from contextlib import closing
from datetime import datetime

import pytest

from app.db import connect, init_db


@pytest.fixture
def history(db_path):
    # More than two default pages, with many equal timestamps.
    with closing(connect(db_path)) as connection:
        records = []
        for index in range(123):
            timestamp = f"2026-08-{1 + index // 10:02d}T12:00:00+00:00"
            transaction_type = "deposit" if index % 2 else "withdrawal"
            transaction_id = connection.execute(
                "INSERT INTO transactions (account_id, type, amount, created_at) VALUES (?, ?, ?, ?)",
                ("ACC-1001", transaction_type, 1.25, timestamp),
            ).lastrowid
            records.append({"id": transaction_id, "type": transaction_type, "created_at": timestamp})
        connection.commit()
    return list(reversed(records))


def test_default_pages_and_last_cursor(client, history):
    response = client.get("/accounts/ACC-1001/transactions")
    assert response.status_code == 200
    page = response.json()
    assert len(page["items"]) == 50
    found = page["items"]
    for expected_size in (50, 23):
        assert isinstance(page["next_cursor"], str)
        response = client.get("/accounts/ACC-1001/transactions", params={"cursor": page["next_cursor"]})
        assert response.status_code == 200
        page = response.json()
        assert len(page["items"]) == expected_size
        found.extend(page["items"])
    assert page["next_cursor"] is None
    assert [item["id"] for item in found] == [item["id"] for item in history]


@pytest.mark.parametrize("limit", [1, 10, 100])
def test_page_limits_with_timestamp_ties(client, history, limit):
    parameters = {"limit": limit}
    ids = []
    for _ in range(124):
        response = client.get("/accounts/ACC-1001/transactions", params=parameters)
        assert response.status_code == 200
        page = response.json()
        assert 0 < len(page["items"]) <= limit
        ids.extend(item["id"] for item in page["items"])
        if page["next_cursor"] is None:
            break
        parameters["cursor"] = page["next_cursor"]
    else:
        pytest.fail("pagination did not terminate")
    assert ids == [item["id"] for item in history]
    assert len(set(ids)) == len(ids)


@pytest.mark.parametrize("limit", ["0", "-1", "101", "1.5", "bad", ""])
def test_invalid_limits(client, limit):
    assert client.get("/accounts/ACC-1001/transactions", params={"limit": limit}).status_code == 422


def test_exact_full_final_page_has_no_cursor(client, history):
    # IDs 111 through 120 are on day 12, exactly filling a ten-item page.
    response = client.get(
        "/accounts/ACC-1001/transactions", params={"from": "2026-08-12", "to": "2026-08-12", "limit": 10}
    )
    assert response.status_code == 200
    assert len(response.json()["items"]) == 10
    assert response.json()["next_cursor"] is None


def test_inserts_between_pages_do_not_shift_snapshot(client, db_path, history):
    first = client.get("/accounts/ACC-1001/transactions", params={"limit": 7}).json()
    ids = [item["id"] for item in first["items"]]
    with closing(connect(db_path)) as connection:
        for timestamp in (
            "2026-09-01T00:00:00+00:00",  # Newest.
            first["items"][-1]["created_at"],  # Same time as boundary.
            "2026-08-02T00:00:00+00:00",  # Backdated into later pages.
        ):
            connection.execute(
                "INSERT INTO transactions (account_id, type, amount, created_at) VALUES (?, ?, ?, ?)",
                ("ACC-1001", "deposit", 99, timestamp),
            )
        connection.commit()
    cursor = first["next_cursor"]
    while cursor:
        response = client.get("/accounts/ACC-1001/transactions", params={"limit": 13, "cursor": cursor})
        assert response.status_code == 200
        page = response.json()
        ids.extend(item["id"] for item in page["items"])
        cursor = page["next_cursor"]
        assert len(ids) <= 123
    assert ids == [item["id"] for item in history]
    fresh = client.get("/accounts/ACC-1001/transactions").json()
    assert fresh["items"][0]["amount"] == "99.00"


def test_filters_are_preserved_through_every_page(client, history):
    parameters = {"from": "2026-08-03", "to": "2026-08-08", "type": "deposit", "limit": 7}
    ids = []
    for _ in range(10):
        response = client.get("/accounts/ACC-1001/transactions", params=parameters)
        assert response.status_code == 200
        page = response.json()
        ids.extend(item["id"] for item in page["items"])
        if page["next_cursor"] is None:
            break
        parameters["cursor"] = page["next_cursor"]
    assert ids == [item["id"] for item in history if item["type"] == "deposit"
                   and "2026-08-03" <= item["created_at"][:10] <= "2026-08-08"]


@pytest.mark.parametrize("cursor", ["", "bad", "a.b.c", "☃", "x" * 4097, "e30.e30"])
def test_invalid_cursor_returns_400(client, cursor):
    assert client.get("/accounts/ACC-1001/transactions", params={"cursor": cursor}).status_code == 400


def test_tampered_cursor_is_rejected(client, history):
    cursor = client.get("/accounts/ACC-1001/transactions").json()["next_cursor"]
    payload, signature = cursor.split(".")
    raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
    changed = raw.replace(b'"snapshot_id":123', b'"snapshot_id":124')
    assert changed != raw
    tampered = base64.urlsafe_b64encode(changed).rstrip(b"=").decode() + "." + signature
    assert client.get("/accounts/ACC-1001/transactions", params={"cursor": tampered}).status_code == 400


@pytest.mark.parametrize("changes", [{"from": "2026-08-02"}, {"to": "2026-08-12"}, {"type": "deposit"}])
def test_cursor_cannot_change_filters(client, history, changes):
    cursor = client.get("/accounts/ACC-1001/transactions").json()["next_cursor"]
    assert client.get("/accounts/ACC-1001/transactions", params={"cursor": cursor, **changes}).status_code == 400


def test_cursor_cannot_change_account(client, history):
    cursor = client.get("/accounts/ACC-1001/transactions").json()["next_cursor"]
    assert client.get("/accounts/ACC-1002/transactions", params={"cursor": cursor}).status_code == 400
    assert client.get("/accounts/missing/transactions", params={"cursor": cursor}).status_code == 404


def test_cursor_replay_and_database_reinitialization(client, db_path, history):
    cursor = client.get("/accounts/ACC-1001/transactions").json()["next_cursor"]
    parameters = {"cursor": cursor}
    expected = client.get("/accounts/ACC-1001/transactions", params=parameters).json()
    with closing(connect(db_path)) as connection:
        init_db(connection)
    replay = client.get("/accounts/ACC-1001/transactions", params=parameters)
    assert replay.status_code == 200
    assert replay.json() == expected


def test_utc_timestamp_formats_and_microseconds_page_in_time_order(client, db_path):
    timestamps = [
        "2026-08-01T12:00:00.000001+00:00",
        "2026-08-01T12:00:00Z",
        "2026-08-01T12:00:00.1+00:00",
        "2026-08-01T12:00:00.000000Z",
        "2026-08-01T12:00:00.100000Z",
        "2026-08-01T12:00:00+00:00",
        "2026-08-01T12:00:00.000002Z",
    ]
    records = []
    with closing(connect(db_path)) as connection:
        for timestamp in timestamps:
            record_id = connection.execute(
                "INSERT INTO transactions (account_id, type, amount, created_at) "
                "VALUES ('ACC-1001', 'deposit', 1, ?)", (timestamp,),
            ).lastrowid
            records.append((record_id, timestamp))
        connection.commit()
    expected = sorted(records, key=lambda item: (datetime.fromisoformat(item[1]), item[0]), reverse=True)
    parameters = {"limit": 2}
    actual = []
    for _ in range(4):
        response = client.get("/accounts/ACC-1001/transactions", params=parameters)
        assert response.status_code == 200
        page = response.json()
        actual.extend((item["id"], item["created_at"]) for item in page["items"])
        if page["next_cursor"] is None:
            break
        parameters["cursor"] = page["next_cursor"]
    assert actual == expected
