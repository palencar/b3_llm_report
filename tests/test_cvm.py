"""Testes para src/b3_etl/cvm.py."""
import hashlib
import io
import os
import zipfile
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

from b3_etl.cvm import parse_companies

# ---------------------------------------------------------------------------
# Helpers para gerar fixtures ZIP em memória
# ---------------------------------------------------------------------------

_CADASTRO_CSV = (
    "CNPJ_CIA;DENOM_SOCIAL;CD_CVM\n"
    "33.000.167/0001-01;PETROBRAS S.A.;9512\n"
    "60.746.948/0001-12;ITAU UNIBANCO HOLDING S.A.;7617\n"
    "33.592.510/0001-03;VALE S.A.;4170\n"
)

_DFP_BPA_CSV = (
    "CNPJ_CIA;DT_REFER;ORDEM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;MOEDA;ESCALA_MOEDA\n"
    "33.000.167/0001-01;2024-12-31;ÚLTIMO;1;Ativo Total;100000;REAL;MIL\n"
    "33.000.167/0001-01;2024-12-31;PENÚLTIMO;1;Ativo Total;90000;REAL;MIL\n"
    "60.746.948/0001-12;2024-12-31;ÚLTIMO;1;Ativo Total;200000;REAL;MIL\n"
    "33.592.510/0001-03;2024-12-31;ÚLTIMO;1;Ativo Total;150000;REAL;MIL\n"
    "33.000.167/0001-01;2024-12-31;ÚLTIMO;1.01;Ativo Circulante;20000;REAL;MIL\n"
)

_ITR_BPA_CSV = (
    "CNPJ_CIA;DT_REFER;ORDEM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;MOEDA;ESCALA_MOEDA\n"
    "33.000.167/0001-01;2024-12-31;ÚLTIMO;1;Ativo Total;99000;REAL;MIL\n"
    "33.000.167/0001-01;2024-12-31;ÚLTIMO;1.02;Novo Campo ITR;5000;REAL;MIL\n"
)


def _zip_bytes(files: dict) -> bytes:
    """Create a ZIP in memory. files: {filename: content_str (latin-1 encoded)}."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content.encode("latin-1"))
    return buf.getvalue()


def _make_cadastro_zip(tmp_path: str) -> str:
    path = os.path.join(tmp_path, "cia_aberta.zip")
    with open(path, "wb") as f:
        f.write(_zip_bytes({"cia_aberta.csv": _CADASTRO_CSV}))
    return path


def _make_dfp_zip(tmp_path: str) -> str:
    path = os.path.join(tmp_path, "dfp_sample.zip")
    with open(path, "wb") as f:
        f.write(_zip_bytes({"dfp_cia_aberta_2024_BPA.csv": _DFP_BPA_CSV}))
    return path


def _make_itr_zip(tmp_path: str) -> str:
    path = os.path.join(tmp_path, "itr_sample.zip")
    with open(path, "wb") as f:
        f.write(_zip_bytes({"itr_cia_aberta_2024_BPA.csv": _ITR_BPA_CSV}))
    return path


def _init_db(db_path: str) -> None:
    from b3_storage.schema import SCHEMA_SQL
    from b3_storage.db import connect
    con = connect(db_path, read_only=False)
    for stmt in SCHEMA_SQL.split(";"):
        stmt = stmt.strip()
        if stmt:
            con.execute(stmt)
    con.close()


# ---------------------------------------------------------------------------
# Task 1: parse_companies
# ---------------------------------------------------------------------------

def test_parse_companies(tmp_path):
    zip_path = _make_cadastro_zip(str(tmp_path))
    result = parse_companies(zip_path)
    assert len(result) == 3
    cnpjs = {r["cnpj"] for r in result}
    assert "33.000.167/0001-01" in cnpjs
    assert "60.746.948/0001-12" in cnpjs
    assert "33.592.510/0001-03" in cnpjs
    petr = next(r for r in result if r["cnpj"] == "33.000.167/0001-01")
    assert petr["name"] == "PETROBRAS S.A."
    assert petr["cd_cvm"] == "9512"


# ---------------------------------------------------------------------------
# Task 2: parse_statements
# ---------------------------------------------------------------------------

from b3_etl.cvm import parse_statements
from datetime import date


def test_parse_statements_dfp(tmp_path):
    """Extrai registros DFP, normaliza ESCALA_MOEDA=MIL e filtra PENÚLTIMO."""
    zip_path = _make_dfp_zip(str(tmp_path))
    result = parse_statements(zip_path, "cvm_dfp")

    # Apenas ÚLTIMO: PETR4(1), PETR4(1.01), ITUB4(1), VALE3(1)  — sem PENÚLTIMO
    assert len(result) == 4
    petr_ativo = next(
        r for r in result
        if r["cnpj"] == "33.000.167/0001-01" and r["account_code"] == "1"
    )
    assert petr_ativo["report_type"] == "BPA"
    assert petr_ativo["period"] == date(2024, 12, 31)
    # 100000 × 1000 (MIL) = 100_000_000
    assert petr_ativo["value"] == 100_000_000.0
    assert petr_ativo["currency"] == "REAL"
    assert petr_ativo["source"] == "cvm_dfp"
    assert petr_ativo["account_name"] == "Ativo Total"


def test_parse_statements_filtra_penultimo(tmp_path):
    """ORDEM_EXERC='PENÚLTIMO' não é incluído no resultado."""
    zip_path = _make_dfp_zip(str(tmp_path))
    result = parse_statements(zip_path, "cvm_dfp")
    # O CSV tem 5 linhas ÚLTIMO e 1 PENÚLTIMO → resultado deve ter 4 (1 PETR4 account_code=1,
    # 1 PETR4 account_code=1.01, 1 ITUB4, 1 VALE3)
    penultimos = [r for r in result if r["account_code"] == "1" and r["cnpj"] == "33.000.167/0001-01"]
    # Deve haver exatamente 1 (o ÚLTIMO), não 2
    assert len(penultimos) == 1
    assert penultimos[0]["value"] == 100_000_000.0
