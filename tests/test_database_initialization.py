import os
import subprocess
import sys
from contextlib import closing
from pathlib import Path

from app.db import connect


def test_initialize_existing_database_preserves_records(tmp_path):
    database_path = str(tmp_path / "existing.db")
    with closing(connect(database_path)) as connection:
        connection.execute(
            "CREATE TABLE accounts (id TEXT PRIMARY KEY, client_name TEXT NOT NULL, "
            "account_number TEXT NOT NULL, balance REAL NOT NULL)"
        )
        connection.execute(
            "INSERT INTO accounts VALUES (?, ?, ?, ?)",
            ("existing", "Synthetic Client", "000000", 125.50),
        )
        connection.commit()
    environment = {**os.environ, "ADVISOR_DB": database_path}
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, "-m", "app.db"],
            cwd=Path(__file__).resolve().parents[1],
            env=environment, capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, result.stderr
    with closing(connect(database_path)) as connection:
        assert tuple(connection.execute("SELECT * FROM accounts").fetchone()) == (
            "existing", "Synthetic Client", "000000", 125.50
        )
        assert connection.execute("SELECT COUNT(*) FROM transfer_requests").fetchone()[0] == 0
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
