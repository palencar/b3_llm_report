"""Ingestão CVM (DFP/ITR) — download, parse e gravação no DuckDB."""
import csv
import hashlib
import io
import os
import re
import time
import urllib.request
import zipfile
from datetime import datetime, timezone

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
