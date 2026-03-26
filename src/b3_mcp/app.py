import os
import time
from datetime import datetime, date, timedelta, timezone
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Header, Query

from b3_core.config import load_config
from b3_core.log import log_info, log_error
from b3_mcp.cache import TTLCache
from b3_storage.db import connect, missing_tables, table_exists


app = FastAPI(title="B3 MCP Server", version="0.1.0")
config = load_config()
cache = TTLCache()

# índice lateral: ticker → última cache_key de fundamentals
_ticker_fund_key: dict[str, str] = {}

_DEFAULT_STATEMENT_TYPES = ["BPA", "BPP", "DRE", "DFC_MI", "DFC_MD"]
_VALID_STATEMENT_TYPES = frozenset({"BPA", "BPP", "DRE", "DFC_MI", "DFC_MD", "DVA", "DMPL", "DRA"})


def _is_stale(last_update, fund_ttl: int) -> bool:
    if last_update is None:
        return True
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return (now - last_update) > timedelta(seconds=fund_ttl)


@app.middleware("http")
async def log_requests(request, call_next):
    start = time.time()
    response = await call_next(request)
    log_info(
        "mcp_request",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=int((time.time() - start) * 1000),
    )
    return response


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise HTTPException(status_code=400, detail="Data invalida. Use YYYY-MM-DD.")


def _require_auth(auth_header: Optional[str]) -> None:
    if not config.auth_token:
        raise HTTPException(status_code=500, detail="AUTH_TOKEN nao configurado.")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token ausente.")
    token = auth_header.split(" ", 1)[1].strip()
    if token != config.auth_token:
        raise HTTPException(status_code=403, detail="Token invalido.")


def _get_db():
    if not os.path.exists(config.db_path):
        raise HTTPException(status_code=503, detail="DuckDB indisponivel.")
    con = connect(config.db_path, read_only=True)
    missing = missing_tables(con)
    if missing:
        con.close()
        raise HTTPException(
            status_code=503,
            detail=f"Tabelas ausentes no DuckDB: {', '.join(missing)}",
        )
    return con


def _latest_period(con, ticker: str, statement_type: str, as_of: Optional[date]) -> Optional[date]:
    if as_of:
        query = """
            SELECT MAX(period)
            FROM fundamentals
            WHERE ticker = ? AND statement_type = ? AND period <= ?
        """
        return con.execute(query, [ticker, statement_type, as_of]).fetchone()[0]
    query = """
        SELECT MAX(period)
        FROM fundamentals
        WHERE ticker = ? AND statement_type = ?
    """
    return con.execute(query, [ticker, statement_type]).fetchone()[0]


def _load_kv(con, ticker: str, statement_type: str, period: date | None) -> dict:
    if not period:
        return {}
    query = """
        SELECT key, value
        FROM fundamentals
        WHERE ticker = ? AND statement_type = ? AND period = ?
    """
    rows = con.execute(query, [ticker, statement_type, period]).fetchall()
    return {key: value for key, value in rows}


def _latest_price(con, ticker: str, as_of: Optional[date]) -> Optional[dict]:
    if as_of:
        query = """
            SELECT ts, close
            FROM prices
            WHERE ticker = ? AND ts <= ?
            ORDER BY ts DESC
            LIMIT 1
        """
        row = con.execute(query, [ticker, datetime.combine(as_of, datetime.min.time())]).fetchone()
    else:
        query = """
            SELECT ts, close
            FROM prices
            WHERE ticker = ?
            ORDER BY ts DESC
            LIMIT 1
        """
        row = con.execute(query, [ticker]).fetchone()
    if not row:
        return None
    return {"value": row[1], "ts": row[0].isoformat()}


def _company_metadata(con, ticker: str) -> dict:
    query = """
        SELECT name, sector, industry, last_update, source
        FROM companies
        WHERE ticker = ?
        LIMIT 1
    """
    row = con.execute(query, [ticker]).fetchone()
    if not row:
        return {}
    return {
        "name": row[0],
        "sector": row[1],
        "industry": row[2],
        "last_update": row[3],          # datetime bruto para cálculo de stale
        "last_update_str": row[3].isoformat() if row[3] else None,  # string para resposta
        "source": row[4],
    }


def _find_ticker_cnpj(con, ticker: str) -> str | None:
    """Return cnpj_digits for ticker from ticker_map, or None if not found."""
    row = con.execute(
        "SELECT cnpj FROM ticker_map WHERE ticker = ? LIMIT 1",
        [ticker],
    ).fetchone()
    return row[0] if row else None


def _load_statements(
    con,
    ticker: str,
    from_year: int,
    to_year: int,
    types: list[str],
) -> dict[str, list[dict]]:
    """Return statements grouped by report_type. Each key maps to a list of records
    ordered by period ASC, account_code ASC. Types without data return empty list."""
    if not types:
        return {}
    placeholders = ", ".join("?" * len(types))  # DuckDB does not support array binding; placeholders are '?' repeated, not user data
    query = f"""
        SELECT s.period, s.report_type, s.account_code, s.account_name,
               s.value, s.currency, s.source
        FROM cvm_statements s
        JOIN cvm_companies c ON c.cnpj = s.cnpj
        -- ticker_map.cnpj is digits-only (normalized by parse_b3_results at ingest)
        JOIN ticker_map t    ON regexp_replace(c.cnpj, '[^0-9]', '', 'g') = t.cnpj
        WHERE t.ticker = ?
          AND s.report_type IN ({placeholders})
          AND EXTRACT(year FROM s.period) BETWEEN ? AND ?
        ORDER BY s.report_type, s.period, s.account_code
    """
    params: list = [ticker] + types + [from_year, to_year]
    rows = con.execute(query, params).fetchall()
    result: dict[str, list[dict]] = {t: [] for t in types}
    for period, report_type, account_code, account_name, value, currency, source in rows:
        if report_type in result:
            result[report_type].append({
                "period": period.isoformat(),
                "account_code": account_code,
                "account_name": account_name,
                "value": value,
                "currency": currency,
                "source": source,
            })
    return result


def _statements_stale(con, fund_ttl: int) -> bool:
    """Return True if cvm_dfp/cvm_itr data in raw_files is older than fund_ttl seconds."""
    row = con.execute(
        "SELECT MAX(fetched_at) FROM raw_files WHERE source IN ('cvm_dfp', 'cvm_itr')"
    ).fetchone()
    last_update = row[0] if row else None
    return _is_stale(last_update, fund_ttl)


@app.get("/v1/health")
def health(authorization: Optional[str] = Header(default=None)) -> dict:
    _require_auth(authorization)
    if not os.path.exists(config.db_path):
        return {"status": "degradado", "last_etl_run": None, "db_size_bytes": 0, "cache_stats": cache.stats()}
    con = connect(config.db_path, read_only=True)
    last_etl_run = None
    if table_exists(con, "companies"):
        row = con.execute("SELECT MAX(last_update) FROM companies").fetchone()
        if row and row[0]:
            last_etl_run = row[0].isoformat()
    size = os.path.getsize(config.db_path)
    con.close()
    return {
        "status": "ok",
        "last_etl_run": last_etl_run,
        "db_size_bytes": size,
        "cache_stats": cache.stats(),
    }


@app.post("/v1/search")
def search(
    body: dict,
    authorization: Optional[str] = Header(default=None),
) -> list[dict]:
    _require_auth(authorization)
    q = (body or {}).get("q", "").strip()
    limit = int((body or {}).get("limit", 10))
    if not q:
        return []

    con = _get_db()
    query = """
        SELECT ticker, name, sector
        FROM companies
        WHERE ticker ILIKE ? OR name ILIKE ?
        LIMIT ?
    """
    rows = con.execute(query, [f"%{q}%", f"%{q}%", limit]).fetchall()
    con.close()
    return [{"ticker": r[0], "name": r[1], "sector": r[2]} for r in rows]


@app.get("/v1/fundamentals/{ticker}")
def fundamentals(
    ticker: str,
    as_of: Optional[str] = Query(default=None),
    modules: Optional[str] = Query(default=None),
    authorization: Optional[str] = Header(default=None),
) -> dict:
    _require_auth(authorization)
    as_of_date = _parse_date(as_of)
    module_list = [m.strip() for m in (modules or "snapshot,income,balance,ratios").split(",") if m.strip()]

    # fallback degradado: se DB inacessível, tenta servir cache stale
    if not os.path.exists(config.db_path):
        fallback_key = _ticker_fund_key.get(ticker)
        if fallback_key:
            cached = cache.get(fallback_key)
            if cached:
                result = dict(cached)
                result["metadata"] = dict(result.get("metadata", {}))
                result["metadata"]["stale"] = True
                return result
        raise HTTPException(status_code=503, detail="DuckDB indisponivel e sem cache.")

    con = _get_db()
    meta = _company_metadata(con, ticker)
    last_update = meta.get("last_update")        # datetime bruto
    last_update_str = meta.get("last_update_str")  # string para resposta

    cache_key = f"fund:{ticker}:{last_update_str}:{as_of}:{','.join(module_list)}"
    cached = cache.get(cache_key)
    if cached:
        con.close()
        return cached

    snapshot = {}
    income = {}
    balance = {}
    ratios = {}
    partial = False

    if "snapshot" in module_list:
        period = _latest_period(con, ticker, "snapshot", as_of_date)
        snapshot = _load_kv(con, ticker, "snapshot", period)
        if not snapshot:
            partial = True
    if "income" in module_list:
        period = _latest_period(con, ticker, "income", as_of_date)
        income = _load_kv(con, ticker, "income", period)
        if not income:
            partial = True
    if "balance" in module_list:
        period = _latest_period(con, ticker, "balance", as_of_date)
        balance = _load_kv(con, ticker, "balance", period)
        if not balance:
            partial = True
    if "ratios" in module_list and table_exists(con, "ratios"):
        if as_of_date:
            query = """
                SELECT ratio_name, value
                FROM (
                    SELECT ratio_name, value,
                        ROW_NUMBER() OVER (PARTITION BY ratio_name ORDER BY period DESC) AS rn
                    FROM ratios
                    WHERE ticker = ? AND period <= ?
                )
                WHERE rn = 1
            """
            rows = con.execute(query, [ticker, as_of_date]).fetchall()
        else:
            query = """
                SELECT ratio_name, value
                FROM (
                    SELECT ratio_name, value,
                        ROW_NUMBER() OVER (PARTITION BY ratio_name ORDER BY period DESC) AS rn
                    FROM ratios
                    WHERE ticker = ?
                )
                WHERE rn = 1
            """
            rows = con.execute(query, [ticker]).fetchall()
        ratios = {name: value for name, value in rows}
        if not ratios:
            partial = True

    price = _latest_price(con, ticker, as_of_date)
    if not price:
        partial = True

    response = {
        "ticker": ticker,
        "as_of": as_of_date.isoformat() if as_of_date else None,
        "snapshot": snapshot if "snapshot" in module_list else {},
        "income": income if "income" in module_list else {},
        "balance": balance if "balance" in module_list else {},
        "ratios": ratios if "ratios" in module_list else {},
        "price": price,
        "metadata": {
            "last_update": last_update_str,
            "stale": _is_stale(last_update, config.fund_ttl),
            "partial": partial,
            "source": meta.get("source"),
            "name": meta.get("name"),
            "sector": meta.get("sector"),
            "industry": meta.get("industry"),
        },
    }

    cache.set(cache_key, response, config.fund_ttl)
    _ticker_fund_key[ticker] = cache_key
    con.close()
    return response


@app.get("/v1/prices/{ticker}")
def prices(
    ticker: str,
    date_from: Optional[str] = Query(default=None, alias="from"),
    date_to: Optional[str] = Query(default=None, alias="to"),
    interval: Optional[str] = Query(default=None),
    authorization: Optional[str] = Header(default=None),
) -> list[dict]:
    _require_auth(authorization)
    from_date = _parse_date(date_from)
    to_date = _parse_date(date_to)
    con = _get_db()

    query = """
        SELECT ts, open, high, low, close, volume
        FROM prices
        WHERE ticker = ?
    """
    params: list[Any] = [ticker]
    if from_date:
        query += " AND ts >= ?"
        params.append(datetime.combine(from_date, datetime.min.time()))
    if to_date:
        query += " AND ts <= ?"
        params.append(datetime.combine(to_date, datetime.min.time()))
    query += " ORDER BY ts ASC"

    rows = con.execute(query, params).fetchall()
    con.close()
    return [
        {
            "ts": r[0].isoformat(),
            "open": r[1],
            "high": r[2],
            "low": r[3],
            "close": r[4],
            "volume": r[5],
            "interval": interval,
        }
        for r in rows
    ]


@app.get("/v1/metadata/{ticker}")
def metadata(
    ticker: str,
    authorization: Optional[str] = Header(default=None),
) -> dict:
    _require_auth(authorization)
    con = _get_db()
    meta = _company_metadata(con, ticker)
    raw = []
    if table_exists(con, "raw_files"):
        query = """
            SELECT source, path, fetched_at, checksum, size_bytes
            FROM raw_files
            WHERE path ILIKE ?
            ORDER BY fetched_at DESC
            LIMIT 50
        """
        rows = con.execute(query, [f"%/{ticker}/%"]).fetchall()
        raw = [
            {
                "source": r[0],
                "path": r[1],
                "fetched_at": r[2].isoformat() if r[2] else None,
                "checksum": r[3],
                "size_bytes": r[4],
            }
            for r in rows
        ]
    con.close()
    return {"ticker": ticker, "company": meta, "raw_files": raw}
