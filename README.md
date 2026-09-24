# advisor-accounts — seed repository

A small FastAPI + SQLite service for advisor client accounts, positions and transfers. The full task is in the challenge document on tenx.

## Setup

Python 3.11 or later.

On macOS or Linux:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest
python seed_db.py           # optional: sample database for local runs
uvicorn app.main:app --reload
```

On Windows PowerShell (activation is not required):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\pytest.exe
.\.venv\Scripts\python.exe seed_db.py
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Run the seed command only for a disposable sample database. To create empty
tables or update an existing database without replacing records, use
`python -m app.db` instead (use the virtual environment's Python on Windows).

Tests use a temporary database per test (see `tests/conftest.py`); they never touch `advisor.db`.

## Layout

| Path | Contents |
| --- | --- |
| `app/main.py` | Application and router registration |
| `app/db.py` | Schema, connection, `get_conn` dependency |
| `app/models.py` | Request and response models |
| `app/routes/accounts.py` | `GET /accounts/{id}`, `GET /accounts/{id}/positions` |
| `app/routes/transfers.py` | `POST /transfers` |
| `app/routes/transactions.py` | Filtered transaction history with cursor pagination |
| `docs/TKT-212.md` | The ticket for Assignment 2, Part A |
| `review/pr_17.diff` | The teammate pull request for Assignment 2, Part B |
| `seed_db.py` | Creates a sample `advisor.db` |

## API conventions

- Money is returned as a string with exactly two decimals, e.g. `"1250.00"`.
- `POST /transfers` accepts `{"from_account", "to_account", "amount"}` and an optional `Idempotency-Key` header. A repeated request with the same key must not move money twice and must return the original response.
- Timestamps are stored and returned as ISO 8601 in UTC.

## Transfer safety

- Amounts must be finite, positive, and expressible in whole cents, up to
  `999999999999.99`. Source and destination accounts must differ (422 otherwise).
- Arithmetic uses `Decimal`. The seed's `REAL` columns remain for compatibility;
  account balances must be non-negative whole-cent values within the same limit
  and must survive conversion to storage and back without losing cents. Invalid
  stored balances or a destination exceeding the limit return 409 without writes.
  This is a bounded compatibility policy, not an exact-money storage migration.
- Transfer writes and saved retry responses commit together. Retrying the same
  key and inputs returns the original response; different inputs with the same
  key return 409. Keys must contain 1–200 characters and cannot be all whitespace.
- SQLite lock contention returns 503 with `Retry-After: 1`. Retry with the same
  idempotency key. Unknown accounts return 404 and insufficient funds return 409.
- Existing databases need `init_db` to add the retry table, pagination indexes,
  and a local cursor signing key before serving traffic.
  Back up the database, then run the following from the repository root. Do not
  rerun `seed_db.py` against data you need to retain: that script replaces it.

```bash
python -m app.db
```

The service still has no authentication or account-ownership authorization.
It is a local exercise using synthetic data, not a production banking service.

## Transaction history

`GET /accounts/{account_id}/transactions` accepts optional `from` and `to`
dates in `YYYY-MM-DD` format. Both dates are inclusive and use UTC. The optional
`type` filter accepts `deposit`, `withdrawal`, `transfer_in`, or `transfer_out`.

`limit` defaults to 50 and must be between 1 and 100. Results are newest first;
the transaction ID breaks ties when timestamps match. UTC timestamps ending in
`Z` or `+00:00` are compared at microsecond precision. Responses contain `items`
and `next_cursor`. Pass the returned cursor with the same account and filters
to request the next page. The limit may change between requests. A null cursor
means there are no more pages.

The first page records the highest existing transaction ID. Later pages exclude
new records, including backdated inserts. Start again without a cursor to see
them. This assumes automatically assigned IDs and unchanged existing records;
it does not preserve rows deleted or edited directly in the database.

Cursors are signed with a random key stored in the local database. Changing a
cursor, account, or filter returns 400. Missing accounts return 404. Invalid
dates, types, or limits return 422. Cursors are not encrypted and do not grant
account access. Keep the database and its backups private.

## Rules

- Do not delete, skip or weaken existing tests. Add tests freely.
- Keep existing response shapes unchanged.
