import duckdb

from .schema import REQUIRED_TABLES


def connect(db_path: str, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(db_path, read_only=read_only)


def table_exists(con: duckdb.DuckDBPyConnection, table_name: str) -> bool:
    query = """
        SELECT COUNT(*) 
        FROM information_schema.tables
        WHERE table_name = ?
    """
    count = con.execute(query, [table_name]).fetchone()[0]
    return count > 0


def missing_tables(con: duckdb.DuckDBPyConnection) -> list[str]:
    missing = []
    for table in REQUIRED_TABLES:
        if not table_exists(con, table):
            missing.append(table)
    return missing
