"""Testes para src/b3_report/sources/cvm.py e integração no prompt."""
import pytest
from datetime import datetime, timezone, date

from b3_storage.schema import SCHEMA_SQL
from b3_storage.db import connect
from b3_report.sources.cvm import get_cvm_data


def _init_con(db_path: str):
    con = connect(db_path, read_only=False)
    for stmt in SCHEMA_SQL.split(";"):
        s = stmt.strip()
        if s:
            con.execute(s)
    return con


def _seed_data(con) -> None:
    con.begin()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    con.execute(
        "INSERT INTO ticker_map VALUES (?, ?, ?, ?)",
        ["33000167000101", "PETR", "PETROBRAS", now],
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
             float(100_000_000 * year), "REAL", "cvm_dfp", now],
        )
        con.execute(
            "INSERT INTO cvm_statements VALUES (?,?,?,?,?,?,?,?,?)",
            ["33.000.167/0001-01", period, "BPA", "1.01", "Ativo Circulante",
             float(30_000_000 * year), "REAL", "cvm_dfp", now],
        )
        # nível 3 — deve ser filtrado
        con.execute(
            "INSERT INTO cvm_statements VALUES (?,?,?,?,?,?,?,?,?)",
            ["33.000.167/0001-01", period, "BPA", "1.01.01", "Caixa e Equivalentes",
             float(10_000_000 * year), "REAL", "cvm_dfp", now],
        )
        con.execute(
            "INSERT INTO cvm_statements VALUES (?,?,?,?,?,?,?,?,?)",
            ["33.000.167/0001-01", period, "DRE", "3.01", "Receita Líquida",
             float(50_000_000 * year), "REAL", "cvm_dfp", now],
        )
    con.execute("COMMIT")


def test_get_cvm_data_retorna_texto(tmp_path):
    db = str(tmp_path / "t.duckdb")
    con = _init_con(db)
    _seed_data(con)
    con.close()
    result = get_cvm_data("PETR4", db)
    assert result != ""
    assert "PETR4" in result
    assert "Ativo Total" in result


def test_get_cvm_data_cnpj_zero_a_esquerda(tmp_path):
    """B3 remove zero à esquerda do CNPJ; CVM mantém. O join normaliza p/ 14 dígitos."""
    db = str(tmp_path / "t.duckdb")
    con = _init_con(db)
    con.begin()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    con.execute(
        "INSERT INTO ticker_map VALUES (?, ?, ?, ?)",
        ["2474103000119", "EGIE", "ENGIE BRASIL ENERGIA S.A.", now],
    )
    con.execute(
        "INSERT INTO cvm_companies VALUES (?, ?, ?, ?)",
        ["02.474.103/0001-19", "ENGIE BRASIL ENERGIA S.A.", "17329", now],
    )
    for year in (2023, 2024, 2025):
        con.execute(
            "INSERT INTO cvm_statements VALUES (?,?,?,?,?,?,?,?,?)",
            ["02.474.103/0001-19", date(year, 12, 31), "BPA", "1",
             "Ativo Total", float(100_000_000 * year), "REAL", "cvm_dfp", now],
        )
    con.execute("COMMIT")
    con.close()
    result = get_cvm_data("EGIE3", db)
    assert result != ""
    assert "Ativo Total" in result


def test_get_cvm_data_filtra_nivel_1_2(tmp_path):
    db = str(tmp_path / "t.duckdb")
    con = _init_con(db)
    _seed_data(con)
    con.close()
    result = get_cvm_data("PETR4", db)
    assert "Ativo Total" in result          # nível 1: presente
    assert "Ativo Circulante" in result     # nível 2: presente
    assert "Caixa e Equivalentes" not in result  # nível 3: filtrado


def test_get_cvm_data_tendencia_3_anos(tmp_path):
    db = str(tmp_path / "t.duckdb")
    con = _init_con(db)
    _seed_data(con)
    con.close()
    result = get_cvm_data("PETR4", db)
    assert "2022=" in result
    assert "2023=" in result
    assert "2024=" in result
    assert "|" in result


def test_get_cvm_data_ticker_nao_encontrado(tmp_path):
    db = str(tmp_path / "t.duckdb")
    con = _init_con(db)
    _seed_data(con)
    con.close()
    assert get_cvm_data("XXXX3", db) == ""


def test_get_cvm_data_db_ausente(tmp_path):
    assert get_cvm_data("PETR4", str(tmp_path / "nao_existe.duckdb")) == ""


from b3_report.prompts import prepare_llm_investment_analysis_request


def test_prompt_inclui_secao_cvm():
    prompt = prepare_llm_investment_analysis_request(
        stock_info="dados yf",
        complementary_info="dados fund",
        analysis_date="2026-03-26",
        cvm_info="Demonstrativos CVM Oficiais — PETR4\nAtivo Total...",
    )
    assert "#### Dados CVM (Demonstrativos Oficiais)" in prompt
    assert "Demonstrativos CVM Oficiais — PETR4" in prompt


def test_prompt_omite_secao_cvm():
    prompt = prepare_llm_investment_analysis_request(
        stock_info="dados yf",
        complementary_info="dados fund",
        analysis_date="2026-03-26",
        cvm_info="",
    )
    assert "#### Dados CVM" not in prompt
