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
