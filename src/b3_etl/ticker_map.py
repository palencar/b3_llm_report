"""Mapeamento CNPJ → ticker via API pública da B3."""
import base64
import json
import os
import re
import time
import urllib.request
from datetime import datetime, timezone

from b3_core.config import Config
from b3_core.log import log_info, log_error
from b3_storage.db import connect, missing_tables

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_B3_API_URL = (
    "https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy"
    "/CompanyCall/GetInitialCompanies/{params}"
)

_CNPJ_RE = re.compile(r"\D")

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_b3_results(results: list[dict]) -> list[dict]:
    """Parse B3 API result list. Returns list of {cnpj, ticker, name}.

    Filters records with empty issuingCompany or cnpj.
    Normalizes CNPJ to digits only.
    """
    out = []
    for r in results:
        ticker = r.get("issuingCompany", "").strip()
        raw_cnpj = r.get("cnpj", "").strip()
        if not ticker or not raw_cnpj:
            continue
        cnpj = _CNPJ_RE.sub("", raw_cnpj)
        if not cnpj:
            continue
        out.append({
            "ticker": ticker,
            "cnpj": cnpj,
            "name": r.get("companyName", "").strip(),
        })
    return out


def fetch_b3_page(page: int, page_size: int = 120, timeout: int = 30) -> dict:
    """Fetch one page from B3 listed companies API.

    Returns dict with {results: [...], totalPages: N}.
    Raises OSError on network failure.
    """
    params = json.dumps(
        {"language": "pt-br", "pageNumber": page, "pageSize": page_size},
        separators=(",", ":"),
    )
    encoded = base64.b64encode(params.encode()).decode()
    url = _B3_API_URL.format(params=encoded)
    req = urllib.request.Request(url, headers={"User-Agent": "b3-llm-report/etl"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run_build_ticker_map(config: Config, skip_db: bool = False) -> int:
    """Fetch B3 listed companies API and upsert ticker_map.

    Returns rc=0 always. Errors are logged and non-fatal.
    """
    log_info("etl_ticker_map_start")
    t0 = time.time()

    con = None
    if not skip_db:
        con = connect(config.db_path, read_only=False)
        missing = missing_tables(con)
        if missing:
            log_error("etl_ticker_map_start", error=f"tabelas ausentes: {missing}")
            con.close()
            return 1

    all_records: list[dict] = []
    total_pages = 1
    page = 1

    while page <= total_pages:
        try:
            data = fetch_b3_page(page)
            total_pages = data.get("totalPages", 1)
            records = parse_b3_results(data.get("results", []))
            all_records.extend(records)
            log_info("etl_ticker_map_page", page=page, total_pages=total_pages, rows=len(records))
        except OSError as exc:
            log_error("etl_ticker_map_page", page=page, error=str(exc))
        page += 1

    if con and all_records:
        fetched_at = datetime.now(timezone.utc).replace(tzinfo=None)
        try:
            con.execute("BEGIN")
            con.executemany(
                "INSERT OR REPLACE INTO ticker_map (cnpj, ticker, name, updated_at)"
                " VALUES (?, ?, ?, ?)",
                [(r["cnpj"], r["ticker"], r["name"], fetched_at) for r in all_records],
            )
            con.execute(
                "INSERT OR REPLACE INTO raw_files"
                " (source, path, fetched_at, checksum, size_bytes) VALUES (?, ?, ?, ?, ?)",
                ["b3_ticker_map", "b3_api_v1", fetched_at, "", 0],
            )
            con.execute("COMMIT")
        except Exception as exc:
            con.execute("ROLLBACK")
            log_error("etl_ticker_map_done", error=str(exc))

    if con:
        con.close()

    duration_ms = int((time.time() - t0) * 1000)
    log_info("etl_ticker_map_done", rows_inserted=len(all_records), duration_ms=duration_ms)
    return 0
