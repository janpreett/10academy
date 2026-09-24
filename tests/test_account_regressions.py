"""Check account responses, including empty and missing accounts."""


def test_account_balance_has_two_decimal_places(client):
    """Return the expected fields and show whole amounts with two decimal places."""
    response = client.get("/accounts/ACC-1001")

    assert response.status_code == 200
    assert response.json() == {
        "id": "ACC-1001", "client_name": "Client One", "balance": "1000.00"
    }


def test_positions_empty_account(client):
    """An existing account with no investments should return an empty list."""
    response = client.get("/accounts/ACC-1002/positions")

    assert response.status_code == 200
    assert response.json() == {"account_id": "ACC-1002", "positions": []}


def test_positions_unknown_account(client):
    """A missing account should return 404, not an empty investment list."""
    assert client.get("/accounts/ACC-9999/positions").status_code == 404
