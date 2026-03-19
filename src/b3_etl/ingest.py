import hashlib
import json
import os
from datetime import datetime, date
from typing import Any, Optional

from b3_core.config import Config
from b3_storage.db import connect, missing_tables, table_exists
from b3_etl.brapi import fetch_quote, BrapiError


def _utc_now() -> datetime:
    return datetime.utcnow()


def _log(level: str, message: str, **fields: Any) -> None:
    payload = {
        "nivel": level,
        "mensagem": message,
        "ts": _utc_now().isoformat() + "Z",
    }
    payload.update(fields)
    print(json.dumps(payload, ensure_ascii=False))


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace("%", "")
        if cleaned == "":
            return None
        # remove milhares e ajusta decimal
        cleaned = cleaned.replace(".", "").replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _parse_period(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        year = int(value)
        if 1900 <= year <= 2100:
            return date(year, 12, 31)
    if isinstance(value, str):
        v = value.strip()
        if v == "":
            return None
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
            try:
                return datetime.strptime(v, fmt).date()
            except ValueError:
                continue
        # tenta apenas ano
        if len(v) == 4 and v.isdigit():
            year = int(v)
            return date(year, 12, 31)
    return None


def _extract_statement_records(
    ticker: str,
    statement: Any,
    statement_type: str,
    currency: Optional[str],
    source: str,
    fetched_at: datetime,
) -> list[dict]:
    records = []
    if not statement:
        return records

    if isinstance(statement, dict):
        # snapshot unico
        period = fetched_at.date()
        for key, value in statement.items():
            if key in ("date", "period", "endDate", "year", "quarter"):
                continue
            val = _safe_float(value)
            if val is None:
                continue
            records.append(
                {
                    "ticker": ticker,
                    "period": period,
                    "statement_type": statement_type,
                    "key": key,
                    "value": val,
                    "currency": currency,
                    "source": source,
                    "fetched_at": fetched_at,
                }
            )
        return records

    if isinstance(statement, list):
        for item in statement:
            if not isinstance(item, dict):
                continue
            period = _parse_period(
                item.get("endDate")
                or item.get("period")
                or item.get("date")
                or item.get("year")
            )
            if period is None:
                continue
            for key, value in item.items():
                if key in ("date", "period", "endDate", "year", "quarter"):
                    continue
                val = _safe_float(value)
                if val is None:
                    continue
                records.append(
                    {
                        "ticker": ticker,
                        "period": period,
                        "statement_type": statement_type,
                        "key": key,
                        "value": val,
                        "currency": currency,
                        "source": source,
                        "fetched_at": fetched_at,
                    }
                )
    return records


def _save_raw(payload: dict, raw_dir: str, source: str, ticker: str, fetched_at: datetime) -> tuple[str, str, int]:
    ts = fetched_at.strftime("%Y%m%dT%H%M%SZ")
    path_dir = os.path.join(raw_dir, source, ticker)
    os.makedirs(path_dir, exist_ok=True)
    path = os.path.join(path_dir, f"{ts}.json")
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
    size_bytes = os.path.getsize(path)
    return path, checksum, size_bytes


def _delete_then_insert(
    con,
    table: str,
    where_cols: list[str],
    where_values: list[Any],
    insert_values: list[Any],
    columns: list[str],
) -> None:
    where_clause = " AND ".join([f"{col} = ?" for col in where_cols])
    con.execute(f"DELETE FROM {table} WHERE {where_clause}", where_values)
    placeholders = ", ".join(["?"] * len(columns))
    cols = ", ".join(columns)
    con.execute(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})", insert_values)


def _write_snapshot(con, snapshot_dir: str, snapshot_date: str) -> None:
    target_dir = os.path.join(snapshot_dir, snapshot_date)
    os.makedirs(target_dir, exist_ok=True)
    tables = ["companies", "fundamentals", "prices", "ratios", "raw_files"]
    for table in tables:
        if not table_exists(con, table):
            continue
        out_path = os.path.join(target_dir, f"{table}.parquet")
        con.execute(f"COPY {table} TO '{out_path}' (FORMAT PARQUET)")


def run_ingest(
    tickers: list[str],
    config: Config,
    modules: list[str],
    write_snapshot: bool = True,
    skip_db: bool = False,
) -> int:
    fetched_at = _utc_now()
    source = "brapi.dev"

    if not tickers:
        _log("erro", "Nenhum ticker informado")
        return 1

    con = None
    missing = []
    if not skip_db:
        os.makedirs(os.path.dirname(config.db_path), exist_ok=True)
        con = connect(config.db_path, read_only=False)
        missing = missing_tables(con)
        if missing:
            _log("erro", "Tabelas ausentes no DuckDB; inicialize o schema antes de ingerir", tabelas=missing)

    os.makedirs(config.raw_dir, exist_ok=True)

    for ticker in tickers:
        try:
            data = fetch_quote(ticker, modules, config.brapi_base_url, config.brapi_key)
        except BrapiError as exc:
            _log("erro", "Falha ao buscar dados", ticker=ticker, detalhe=str(exc))
            continue

        results = data.get("results") or []
        if not results:
            _log("erro", "Resposta BRAPI sem resultados", ticker=ticker)
            continue

        payload = results[0]
        currency = payload.get("currency")
        last_update = fetched_at

        raw_path, checksum, size_bytes = _save_raw(data, config.raw_dir, "brapi", ticker, fetched_at)

        if con and not missing:
            try:
                con.execute("BEGIN")

                _delete_then_insert(
                    con,
                    "companies",
                    ["ticker"],
                    [ticker],
                    [
                        ticker,
                        payload.get("shortName") or payload.get("longName"),
                        payload.get("sector"),
                        payload.get("industry"),
                        last_update,
                        source,
                        fetched_at,
                    ],
                    ["ticker", "name", "sector", "industry", "last_update", "source", "updated_at"],
                )

                # prices (apenas ultimo preco)
                price_ts = payload.get("regularMarketTime")
                if isinstance(price_ts, (int, float)):
                    price_ts = datetime.utcfromtimestamp(price_ts)
                else:
                    price_ts = fetched_at

                _delete_then_insert(
                    con,
                    "prices",
                    ["ticker", "ts"],
                    [ticker, price_ts],
                    [
                        ticker,
                        price_ts,
                        _safe_float(payload.get("regularMarketOpen")),
                        _safe_float(payload.get("regularMarketDayHigh")),
                        _safe_float(payload.get("regularMarketDayLow")),
                        _safe_float(payload.get("regularMarketPrice")),
                        payload.get("regularMarketVolume"),
                        source,
                    ],
                    ["ticker", "ts", "open", "high", "low", "close", "volume", "source"],
                )

                # fundamentals
                fundamentals_records = []
                fundamentals_records += _extract_statement_records(
                    ticker,
                    payload.get("financialData"),
                    "snapshot",
                    currency,
                    source,
                    fetched_at,
                )
                fundamentals_records += _extract_statement_records(
                    ticker,
                    payload.get("balanceSheetHistory"),
                    "balance",
                    currency,
                    source,
                    fetched_at,
                )
                fundamentals_records += _extract_statement_records(
                    ticker,
                    payload.get("incomeStatementHistory"),
                    "income",
                    currency,
                    source,
                    fetched_at,
                )

                for rec in fundamentals_records:
                    _delete_then_insert(
                        con,
                        "fundamentals",
                        ["ticker", "period", "statement_type", "key"],
                        [
                            rec["ticker"],
                            rec["period"],
                            rec["statement_type"],
                            rec["key"],
                        ],
                        [
                            rec["ticker"],
                            rec["period"],
                            rec["statement_type"],
                            rec["key"],
                            rec["value"],
                            rec["currency"],
                            rec["source"],
                            rec["fetched_at"],
                        ],
                        [
                            "ticker",
                            "period",
                            "statement_type",
                            "key",
                            "value",
                            "currency",
                            "source",
                            "fetched_at",
                        ],
                    )

                _delete_then_insert(
                    con,
                    "raw_files",
                    ["source", "path"],
                    [source, raw_path],
                    [source, raw_path, fetched_at, checksum, size_bytes],
                    ["source", "path", "fetched_at", "checksum", "size_bytes"],
                )

                con.execute("COMMIT")
            except Exception as exc:
                con.execute("ROLLBACK")
                _log("erro", "Falha ao escrever no DuckDB", ticker=ticker, detalhe=str(exc))
                continue

        _log(
            "info",
            "Ticker ingerido",
            ticker=ticker,
            snapshot_registros=len(payload),
            fundamentals=len(fundamentals_records),
        )

    if con and not missing and write_snapshot:
        snapshot_date = fetched_at.strftime("%Y%m%d")
        _write_snapshot(con, config.snapshot_dir, snapshot_date)
        _log("info", "Snapshot gerado", data=snapshot_date, destino=config.snapshot_dir)

    if con:
        con.close()
    return 0
