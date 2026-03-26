"""Testes para helpers e rota /v1/statements em src/b3_mcp/app.py."""
import os
import pytest
from datetime import datetime, timezone, date, timedelta
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from b3_storage.schema import SCHEMA_SQL
from b3_storage.db import connect
from b3_mcp.app import app, _find_ticker_cnpj, _load_statements, _statements_stale


# ---------------------------------------------------------------------------
# Helpers de fixture
# ---------------------------------------------------------------------------

def _init_con(db_path: str):
    con = connect(db_path, read_only=False)
    for stmt in SCHEMA_SQL.split(";"):
        s = stmt.strip()
        if s:
            con.execute(s)
    return con


def _seed_data(con) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    con.execute(
        "INSERT INTO ticker_map VALUES (?, ?, ?, ?)",
        ["33000167000101", "PETR4", "PETROBRAS", now],
    )
    con.execute(
        "INSERT INTO cvm_companies VALUES (?, ?, ?, ?)",
        ["33.000.167/0001-01", "PETROBRAS S.A.", "9512", now],
    )
    for year in (2022, 2023, 2024):
        period = date(year, 12, 31)
        con.execute(
            "INSERT INTO cvm_statements VALUES (?,?,?,?,?,?,?,?,?)",
            ["33.000.167/0001-01", period, "BPA", "1", "Ativo Total",
             float(100_000 * year), "REAL", "cvm_dfp", now],
        )
        con.execute(
            "INSERT INTO cvm_statements VALUES (?,?,?,?,?,?,?,?,?)",
            ["33.000.167/0001-01", period, "DRE", "3.01", "Receita Líquida",
             float(50_000 * year), "REAL", "cvm_dfp", now],
        )


# ---------------------------------------------------------------------------
# Testes: _find_ticker_cnpj
# ---------------------------------------------------------------------------

def test_find_ticker_cnpj_encontrado(tmp_path):
    con = _init_con(str(tmp_path / "t.duckdb"))
    _seed_data(con)
    assert _find_ticker_cnpj(con, "PETR4") == "33000167000101"
    con.close()


def test_find_ticker_cnpj_nao_encontrado(tmp_path):
    con = _init_con(str(tmp_path / "t.duckdb"))
    _seed_data(con)
    assert _find_ticker_cnpj(con, "XXXX3") is None
    con.close()


# ---------------------------------------------------------------------------
# Testes: _load_statements
# ---------------------------------------------------------------------------

def test_load_statements_retorna_agrupado(tmp_path):
    con = _init_con(str(tmp_path / "t.duckdb"))
    _seed_data(con)
    result = _load_statements(con, "PETR4", 2022, 2024, ["BPA", "DRE"])
    assert set(result.keys()) == {"BPA", "DRE"}
    assert len(result["BPA"]) == 3   # 2022, 2023, 2024
    assert len(result["DRE"]) == 3
    periods = [r["period"] for r in result["BPA"]]
    assert periods == ["2022-12-31", "2023-12-31", "2024-12-31"]
    con.close()


def test_load_statements_filtro_periodo(tmp_path):
    con = _init_con(str(tmp_path / "t.duckdb"))
    _seed_data(con)
    result = _load_statements(con, "PETR4", 2023, 2023, ["BPA"])
    assert len(result["BPA"]) == 1
    assert result["BPA"][0]["period"] == "2023-12-31"
    con.close()


def test_load_statements_tipo_sem_dados_retorna_lista_vazia(tmp_path):
    con = _init_con(str(tmp_path / "t.duckdb"))
    _seed_data(con)
    result = _load_statements(con, "PETR4", 2022, 2024, ["BPP"])
    assert result["BPP"] == []
    con.close()


def test_load_statements_campos_corretos(tmp_path):
    con = _init_con(str(tmp_path / "t.duckdb"))
    _seed_data(con)
    result = _load_statements(con, "PETR4", 2024, 2024, ["BPA"])
    rec = result["BPA"][0]
    assert rec["period"] == "2024-12-31"
    assert rec["account_code"] == "1"
    assert rec["account_name"] == "Ativo Total"
    assert rec["value"] == 100_000 * 2024
    assert rec["currency"] == "REAL"
    assert rec["source"] == "cvm_dfp"
    con.close()


# ---------------------------------------------------------------------------
# Testes: _statements_stale
# ---------------------------------------------------------------------------

def test_statements_stale_sem_raw_files(tmp_path):
    con = _init_con(str(tmp_path / "t.duckdb"))
    assert _statements_stale(con, 86400) is True
    con.close()


def test_statements_stale_false_com_dados_recentes(tmp_path):
    con = _init_con(str(tmp_path / "t.duckdb"))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    con.execute(
        "INSERT INTO raw_files VALUES (?, ?, ?, ?, ?)",
        ["cvm_dfp", "/raw/cvm/2024/dfp.zip", now, "abc", 1024],
    )
    assert _statements_stale(con, 86400) is False
    con.close()


def test_statements_stale_true_com_dados_antigos(tmp_path):
    con = _init_con(str(tmp_path / "t.duckdb"))
    old = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=30)
    con.execute(
        "INSERT INTO raw_files VALUES (?, ?, ?, ?, ?)",
        ["cvm_dfp", "/raw/cvm/2024/dfp.zip", old, "abc", 1024],
    )
    assert _statements_stale(con, 86400) is True
    con.close()
