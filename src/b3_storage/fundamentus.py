"""Cache helpers for fundamentus_cache table.

Uses duckdb with read_only=True (load_cache/latest_fetch) or read_only=False
(save_cache). Follows the same connection pattern as src/b3_storage/db.py.
"""
import duckdb
from datetime import datetime
from typing import Optional


def save_cache(db_path: str, ticker: str, indicators: dict[str, str], fetched_at: datetime) -> None:
    """Substitui atomicamente todos os indicadores da coleta de um ticker."""
    con = duckdb.connect(db_path, read_only=False)
    con.execute("CREATE TABLE IF NOT EXISTS fundamentus_cache (ticker TEXT NOT NULL, label TEXT NOT NULL, value TEXT, source TEXT DEFAULT 'fundamentus.com.br', fetched_at TIMESTAMP, PRIMARY KEY (ticker, label))")
    try:
        con.execute("BEGIN TRANSACTION")
        con.execute("DELETE FROM fundamentus_cache WHERE ticker = ?", [ticker])
        for label, value in indicators.items():
            con.execute(
                "INSERT OR REPLACE INTO fundamentus_cache (ticker, label, value, source, fetched_at) VALUES (?, ?, ?, ?, ?)",
                [ticker, label, value, "fundamentus.com.br", fetched_at],
            )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def load_cache(db_path: str, ticker: str) -> Optional[dict[str, str]]:
    """Return label→value dict if cache exists for ticker, else None."""
    con = duckdb.connect(db_path, read_only=True)
    try:
        rows = con.execute(
            "SELECT label, value FROM fundamentus_cache WHERE ticker = ? "
            "AND fetched_at = (SELECT MAX(fetched_at) FROM fundamentus_cache WHERE ticker = ?) ORDER BY label",
            [ticker, ticker],
        ).fetchall()
        return {label: value for label, value in rows} if rows else None
    finally:
        con.close()


def latest_fetch(db_path: str, ticker: str) -> Optional[datetime]:
    """Return fetched_at of most recent fetch for ticker, or None."""
    con = duckdb.connect(db_path, read_only=True)
    try:
        row = con.execute(
            "SELECT MAX(fetched_at) FROM fundamentus_cache WHERE ticker = ?",
            [ticker],
        ).fetchone()
        return row[0] if row and row[0] else None
    finally:
        con.close()
