"""Ingestão CVM (DFP/ITR) — download, parse e gravação no DuckDB."""
import csv
import hashlib
import io
import os
import re
import time
import urllib.request
import zipfile
from datetime import date, datetime, timezone

from b3_core.config import Config
from b3_core.log import log_info, log_error
from b3_storage.db import connect, missing_tables

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_REPORT_TYPES = frozenset({"BPA", "BPP", "DRE", "DFC_MI", "DFC_MD", "DVA", "DMPL", "DRA"})

_SCALE = {"UNIDADE": 1, "MIL": 1_000, "MILHÃO": 1_000_000}

_CADASTRO_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cia_aberta.zip"
_DFP_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_{year}.zip"
_ITR_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/itr_cia_aberta_{year}.zip"

# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _extract_report_type(filename: str) -> str | None:
    """Extract report type from CSV filename.

    Examples:
        'dfp_cia_aberta_2024_BPA_con.csv' → 'BPA'
        'itr_cia_aberta_2024_DFC_MI.csv'  → 'DFC_MI'
    """
    upper = filename.upper()
    # Try multi-word types first to avoid partial matches (DFC_MI before DFC)
    for rt in sorted(_REPORT_TYPES, key=len, reverse=True):
        if re.search(rf"_{re.escape(rt)}[_.]", upper):
            return rt
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_statements(zip_path: str, source: str) -> list[dict]:
    """Parse DFP/ITR ZIP. Returns list of statement records.

    Filters ORDEM_EXERC == 'ÚLTIMO'. Normalizes VL_CONTA by ESCALA_MOEDA.
    period is returned as datetime.date.
    """
    result = []
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if not name.lower().endswith(".csv"):
                continue
            report_type = _extract_report_type(name)
            if report_type is None:
                continue
            with zf.open(name) as raw:
                reader = csv.DictReader(
                    io.TextIOWrapper(raw, encoding="latin-1"), delimiter=";"
                )
                for row in reader:
                    if row.get("ORDEM_EXERC", "").strip() != "ÚLTIMO":
                        continue
                    cnpj = row.get("CNPJ_CIA", "").strip()
                    dt_refer = row.get("DT_REFER", "").strip()
                    cd_conta = row.get("CD_CONTA", "").strip()
                    ds_conta = row.get("DS_CONTA", "").strip()
                    vl_conta = row.get("VL_CONTA", "").strip()
                    moeda = row.get("MOEDA", "REAL").strip()
                    escala = row.get("ESCALA_MOEDA", "UNIDADE").strip()
                    if not cnpj or not dt_refer or not vl_conta:
                        continue
                    try:
                        period = datetime.strptime(dt_refer, "%Y-%m-%d").date()
                    except ValueError:
                        continue
                    try:
                        value = float(vl_conta.replace(",", ".")) * _SCALE.get(escala, 1)
                    except ValueError:
                        continue
                    result.append({
                        "cnpj": cnpj,
                        "period": period,
                        "report_type": report_type,
                        "account_code": cd_conta,
                        "account_name": ds_conta,
                        "value": value,
                        "currency": moeda,
                        "source": source,
                    })
    return result


def parse_companies(zip_path: str) -> list[dict]:
    """Parse cia_aberta.zip. Returns list of {cnpj, name, cd_cvm}."""
    result = []
    with zipfile.ZipFile(zip_path) as zf:
        csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not csv_names:
            return result
        with zf.open(csv_names[0]) as raw:
            reader = csv.DictReader(
                io.TextIOWrapper(raw, encoding="latin-1"), delimiter=";"
            )
            for row in reader:
                cnpj = row.get("CNPJ_CIA", "").strip()
                if not cnpj:
                    continue
                result.append({
                    "cnpj": cnpj,
                    "name": row.get("DENOM_SOCIAL", "").strip(),
                    "cd_cvm": row.get("CD_CVM", "").strip(),
                })
    return result


def download_zip(url: str, dest_path: str, timeout: int = 60) -> tuple[str, int]:
    """Download ZIP from url to dest_path. Returns (checksum_sha256, size_bytes).

    Raises OSError on network failure.
    """
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "b3-llm-report/etl"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    with open(dest_path, "wb") as f:
        f.write(data)
    return hashlib.sha256(data).hexdigest(), len(data)


def _download_or_skip(
    url: str,
    dest_path: str,
    con,
    source: str,
    timeout: int = 60,
) -> tuple[str, int, bool]:
    """Download ZIP or skip if already cached in raw_files with matching checksum.

    con: DuckDB connection or None (skip_db mode → always download).
    Returns (checksum, size_bytes, was_downloaded).
    """
    if con is not None and os.path.isfile(dest_path):
        row = con.execute(
            "SELECT checksum FROM raw_files WHERE source = ? AND path = ?",
            [source, dest_path],
        ).fetchone()
        if row:
            with open(dest_path, "rb") as f:
                local_checksum = hashlib.sha256(f.read()).hexdigest()
            if local_checksum == row[0]:
                return local_checksum, os.path.getsize(dest_path), False
    checksum, size_bytes = download_zip(url, dest_path, timeout=timeout)
    return checksum, size_bytes, True


def run_ingest_cvm(
    year: int,
    include_itr: bool,
    config: Config,
    skip_db: bool = False,
) -> int:
    """Orchestrate CVM ingestion: cadastro → DFP → ITR (optional).

    Returns rc=0 always. Errors are logged and non-fatal.
    """
    log_info("etl_cvm_start", year=year, include_itr=include_itr)
    t0 = time.time()

    con = None
    if not skip_db:
        con = connect(config.db_path, read_only=False)
        missing = missing_tables(con)
        if missing:
            log_error("etl_cvm_start", error=f"tabelas ausentes: {missing}")
            con.close()
            return 1

    fetched_at = datetime.now(timezone.utc).replace(tzinfo=None)
    rows_companies = 0
    rows_statements = 0

    cvm_dir = os.path.join(config.raw_dir, "cvm")
    cadastro_path = os.path.join(cvm_dir, "cadastro", "cia_aberta.zip")
    dfp_path = os.path.join(cvm_dir, str(year), f"dfp_cia_aberta_{year}.zip")
    itr_path = os.path.join(cvm_dir, str(year), f"itr_cia_aberta_{year}.zip")

    # 1. Cadastro
    try:
        checksum, size_bytes, _ = _download_or_skip(
            _CADASTRO_URL, cadastro_path, con, "cvm_cadastro"
        )
        companies = parse_companies(cadastro_path)
        log_info("etl_cvm_zip", type="cadastro", rows=len(companies), size_bytes=size_bytes)
        if con and companies:
            try:
                con.execute("BEGIN")
                con.executemany(
                    "INSERT OR REPLACE INTO cvm_companies"
                    " (cnpj, name, cd_cvm, fetched_at) VALUES (?, ?, ?, ?)",
                    [(c["cnpj"], c["name"], c["cd_cvm"], fetched_at) for c in companies],
                )
                con.execute(
                    "INSERT OR REPLACE INTO raw_files"
                    " (source, path, fetched_at, checksum, size_bytes) VALUES (?, ?, ?, ?, ?)",
                    ["cvm_cadastro", cadastro_path, fetched_at, checksum, size_bytes],
                )
                con.execute("COMMIT")
                rows_companies = len(companies)
            except Exception as exc:
                con.execute("ROLLBACK")
                log_error("etl_cvm_zip", type="cadastro", error=str(exc))
    except OSError as exc:
        log_error("etl_cvm_zip", type="cadastro", error=str(exc))

    # 2. DFP
    try:
        checksum, size_bytes, _ = _download_or_skip(
            _DFP_URL.format(year=year), dfp_path, con, "cvm_dfp"
        )
        dfp_records = parse_statements(dfp_path, "cvm_dfp")
        log_info("etl_cvm_zip", type="dfp", year=year, rows=len(dfp_records), size_bytes=size_bytes)
        if con and dfp_records:
            try:
                con.execute("BEGIN")
                con.executemany(
                    "INSERT OR REPLACE INTO cvm_statements"
                    " (cnpj, period, report_type, account_code, account_name,"
                    "  value, currency, source, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (r["cnpj"], r["period"], r["report_type"], r["account_code"],
                         r["account_name"], r["value"], r["currency"], r["source"], fetched_at)
                        for r in dfp_records
                    ],
                )
                con.execute(
                    "INSERT OR REPLACE INTO raw_files"
                    " (source, path, fetched_at, checksum, size_bytes) VALUES (?, ?, ?, ?, ?)",
                    ["cvm_dfp", dfp_path, fetched_at, checksum, size_bytes],
                )
                con.execute("COMMIT")
                rows_statements += len(dfp_records)
            except Exception as exc:
                con.execute("ROLLBACK")
                log_error("etl_cvm_zip", type="dfp", error=str(exc))
    except OSError as exc:
        log_error("etl_cvm_zip", type="dfp", error=str(exc))

    # 3. ITR (optional)
    if include_itr:
        try:
            checksum, size_bytes, _ = _download_or_skip(
                _ITR_URL.format(year=year), itr_path, con, "cvm_itr"
            )
            itr_records = parse_statements(itr_path, "cvm_itr")
            if con:
                existing = con.execute(
                    "SELECT cnpj, period, report_type, account_code"
                    " FROM cvm_statements WHERE source = 'cvm_dfp'"
                    " AND period >= ? AND period < ?",
                    [date(year, 1, 1), date(year + 1, 1, 1)],
                ).fetchall()
                existing_set = {(r[0], r[1], r[2], r[3]) for r in existing}
                to_insert = [
                    r for r in itr_records
                    if (r["cnpj"], r["period"], r["report_type"], r["account_code"])
                    not in existing_set
                ]
                log_info(
                    "etl_cvm_zip", type="itr", year=year,
                    rows_parsed=len(itr_records), rows_inserted=len(to_insert),
                    size_bytes=size_bytes,
                )
                try:
                    con.execute("BEGIN")
                    if to_insert:
                        con.executemany(
                            "INSERT OR REPLACE INTO cvm_statements"
                            " (cnpj, period, report_type, account_code, account_name,"
                            "  value, currency, source, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            [
                                (r["cnpj"], r["period"], r["report_type"], r["account_code"],
                                 r["account_name"], r["value"], r["currency"], r["source"], fetched_at)
                                for r in to_insert
                            ],
                        )
                    con.execute(
                        "INSERT OR REPLACE INTO raw_files"
                        " (source, path, fetched_at, checksum, size_bytes) VALUES (?, ?, ?, ?, ?)",
                        ["cvm_itr", itr_path, fetched_at, checksum, size_bytes],
                    )
                    con.execute("COMMIT")
                    rows_statements += len(to_insert)
                except Exception as exc:
                    con.execute("ROLLBACK")
                    log_error("etl_cvm_zip", type="itr", error=str(exc))
        except OSError as exc:
            log_error("etl_cvm_zip", type="itr", error=str(exc))

    if con:
        con.close()

    duration_ms = int((time.time() - t0) * 1000)
    log_info(
        "etl_cvm_done",
        rows_companies=rows_companies,
        rows_statements=rows_statements,
        duration_ms=duration_ms,
    )
    return 0
