import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app.db import get_conn
from app.money import format_money, read_money

router = APIRouter()


@router.get("/accounts/{account_id}")
def get_account(account_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    row = conn.execute(
        "SELECT id, client_name, balance FROM accounts WHERE id = ?", (account_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="account not found")
    return {
        "id": row["id"],
        "client_name": row["client_name"],
        "balance": format_money(read_money(row["balance"])),
    }


@router.get("/accounts/{account_id}/positions")
def get_positions(account_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    if conn.execute("SELECT 1 FROM accounts WHERE id = ?", (account_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="account not found")
    positions = conn.execute(
        """
        SELECT positions.fund_code, positions.units, funds.name, funds.nav
        FROM positions
        JOIN funds ON funds.code = positions.fund_code
        WHERE positions.account_id = ?
        ORDER BY positions.fund_code
        """,
        (account_id,),
    ).fetchall()
    result = []
    for position in positions:
        result.append(
            {
                "fund_code": position["fund_code"],
                "fund_name": position["name"],
                "units": f"{position['units']:.4f}",
                "market_value": f"{position['units'] * position['nav']:.2f}",
            }
        )
    return {"account_id": account_id, "positions": result}
