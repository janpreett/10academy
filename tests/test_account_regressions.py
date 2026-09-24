def test_account_balance_has_two_decimal_places(client):
    response = client.get("/accounts/ACC-1001")

    assert response.status_code == 200
    assert response.json() == {
        "id": "ACC-1001", "client_name": "Client One", "balance": "1000.00"
    }


def test_positions_empty_account(client):
    response = client.get("/accounts/ACC-1002/positions")

    assert response.status_code == 200
    assert response.json() == {"account_id": "ACC-1002", "positions": []}


def test_positions_unknown_account(client):
    assert client.get("/accounts/ACC-9999/positions").status_code == 404
