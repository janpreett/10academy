"""SQLite access. One connection per request via the get_conn dependency."""
import os
import secrets
import sqlite3
from contextlib import closing, contextmanager
from typing import Iterator

from app.timestamps import UTC_SORT_KEY

DB_PATH = os.environ.get("ADVISOR_DB", "advisor.db")


class DatabaseBusyError(Exception):
    """A competing SQLite transaction exceeded the connection's lock timeout."""

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    client_name TEXT NOT NULL,
    account_number TEXT NOT NULL,
    balance REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS funds (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    nav REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL REFERENCES accounts(id),
    fund_code TEXT NOT NULL REFERENCES funds(code),
    units REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS transfers (
    id TEXT PRIMARY KEY,
    from_account TEXT NOT NULL REFERENCES accounts(id),
    to_account TEXT NOT NULL REFERENCES accounts(id),
    amount REAL NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL REFERENCES accounts(id),
    type TEXT NOT NULL CHECK (type IN ('deposit', 'withdrawal', 'transfer_in', 'transfer_out')),
    amount REAL NOT NULL,
    created_at TEXT NOT NULL,
    transfer_id TEXT REFERENCES transfers(id)
);
CREATE TABLE IF NOT EXISTS transfer_requests (
    idempotency_key TEXT PRIMARY KEY NOT NULL,
    from_account TEXT NOT NULL REFERENCES accounts(id),
    to_account TEXT NOT NULL REFERENCES accounts(id),
    amount TEXT NOT NULL,
    transfer_id TEXT NOT NULL UNIQUE REFERENCES transfers(id),
    from_balance TEXT NOT NULL,
    to_balance TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS transactions_account_utc_order
    ON transactions(account_id, ({UTC_SORT_KEY}) DESC, id DESC);
CREATE INDEX IF NOT EXISTS transactions_account_id
    ON transactions(account_id, id DESC);
CREATE INDEX IF NOT EXISTS transactions_account_type_utc_order
    ON transactions(account_id, type, ({UTC_SORT_KEY}) DESC, id DESC);
CREATE TABLE IF NOT EXISTS cursor_signing_key (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    secret BLOB NOT NULL CHECK (length(secret) = 32)
);
"""


def connect(path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    # A database-owned key keeps cursors valid across restarts and workers.
    # It is generated locally, never hardcoded or included in responses.
    conn.execute(
        "INSERT OR IGNORE INTO cursor_signing_key (id, secret) VALUES (1, ?)",
        (secrets.token_bytes(32),),
    )
    conn.commit()


@contextmanager
def write_transaction(connection: sqlite3.Connection) -> Iterator[None]:
    # Acquire the write reservation before reading any balances or retry keys.
    try:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            yield
    except sqlite3.OperationalError as error:
        # Extended SQLite codes keep their primary code in the low byte.
        error_code = getattr(error, "sqlite_errorcode", 0) & 0xFF
        if error_code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            raise DatabaseBusyError() from error
        raise


def get_conn() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


if __name__ == "__main__":
    # Add missing tables without deleting existing seed or account records.
    with closing(connect()) as connection:
        init_db(connection)
