"""Testes para src/b3_report/sources/fundamentus.py (arquitetura cache-first)."""
import os
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from b3_core.fundamentus import LABEL_TO_KEY
from b3_report.sources.fundamentus import get_complementary_data


_FAKE_INDICATORS = {
    "Empresa": "PETROBRAS S.A.",
    "Setor": "Petróleo e Gás",
    "Subsetor": "Exploração e Produção",
    "Cotação": "49,41",
    "Data últ cot": "28/03/2026",
    "Min 52 sem": "30,10",
    "Max 52 sem": "49,44",
    "Vol $ méd (2m)": "98.765.432",
    "Valor de mercado": "636.800.000.000",
    "Valor da firma": "700.000.000.000",
    "Nro. Ações": "13.000.000.000",
    "P/L": "8,53",
    "P/VP": "1,24",
    "P/EBIT": "5,87",
    "PSR": "2,01",
    "P/Ativos": "0,62",
    "P/Cap. Giro": "6,34",
    "P/Ativ Circ Liq": "3,91",
    "Div. Yield": "12,34%",
    "EV / EBITDA": "4,31",
    "EV / EBIT": "5,12",
    "ROE": "14,56%",
    "ROIC": "11,23%",
    "Marg. Bruta": "53,12%",
    "Marg. EBIT": "37,01%",
    "Marg. Líquida": "23,64%",
    "EBIT": "195.000.000",
    "Receita Líquida": "527.000.000",
    "Lucro Líquido": "124.600.000",
    "Dia": "-0,52%",
    "Mês": "+3,87%",
    "30 dias": "+12,34%",
    "12 meses": "+28,91%",
    "EBIT_1": "780.000.000",
    "Receita Líquida_1": "2.100.000.000",
    "Lucro Líquido_1": "490.000.000",
    "Ativo": "980.000.000",
    "Patrim. Líq": "360.000.000",
    "Dív. Bruta": "320.000.000",
    "Disponibilidades": "68.000.000",
    "Liquidez Corr": "1,45",
    "Div Br/ Patrim": "0,89",
}


def _seed_temp_db(ticker: str = "PETR4") -> str:
    """Create a temp DuckDB file with fundamentus_cache seeded."""
    import duckdb

    path = tempfile.mktemp(suffix=".duckdb")
    con = duckdb.connect(path, read_only=False)
    try:
        con.execute(
            "CREATE TABLE IF NOT EXISTS fundamentus_cache ("
            "ticker TEXT NOT NULL, label TEXT NOT NULL, value TEXT, "
            "source TEXT DEFAULT 'fundamentus.com.br', "
            "fetched_at TIMESTAMP, PRIMARY KEY (ticker, label))"
        )
        ts = datetime.now() - timedelta(hours=1)
        for label, value in _FAKE_INDICATORS.items():
            con.execute(
                "INSERT INTO fundamentus_cache (ticker, label, value, fetched_at) VALUES (?, ?, ?, ?)",
                [ticker, label, value, ts],
            )
    finally:
        con.close()
    return path


# ------------------------------------------------------------------ cache-hit
def test_get_complementary_data_cache_hit():
    """Quando há dados válidos no cache → usa e retorna texto formatado."""
    db_path = _seed_temp_db("PETR4")
    try:
        result = get_complementary_data("PETR4", db_path=db_path, ttl_seconds=86400)
        assert "PETR4" in result
        assert "Dados de Mercado" in result
        assert "Múltiplos de Valuation" in result
        assert "Rentabilidade" in result
        assert "Balanço e DRE (Fundamentus)" in result
        assert "Oscilações" in result
        assert "PETROBRAS S.A." in result
        assert "12,34%" in result
    finally:
        os.unlink(db_path)


def test_get_complementary_data_cache_hit_omite_faltantes():
    """Campos ausentes no cache não aparecem na saída."""
    # Cache parcial: só labels essenciais
    import duckdb

    path = tempfile.mktemp(suffix=".duckdb")
    con = duckdb.connect(path, read_only=False)
    try:
        con.execute(
            "CREATE TABLE IF NOT EXISTS fundamentus_cache ("
            "ticker TEXT NOT NULL, label TEXT NOT NULL, value TEXT, "
            "source TEXT DEFAULT 'fundamentus.com.br', "
            "fetched_at TIMESTAMP, PRIMARY KEY (ticker, label))"
        )
        ts = datetime.now() - timedelta(hours=1)
        for label in ["P/L", "ROE", "Marg. Bruta"]:
            con.execute(
                "INSERT INTO fundamentus_cache (ticker, label, value, fetched_at) VALUES (?, ?, ?, ?)",
                ["PETR4", label, "valor", ts],
            )
    finally:
        con.close()

    try:
        result = get_complementary_data("PETR4", db_path=path, ttl_seconds=86400)
        # Seções com dados devem aparecer
        assert "Múltiplos de Valuation" in result
        assert "Rentabilidade" in result
    finally:
        os.unlink(path)


# --------------------------------------------------------------- cache-miss (fetch)
def test_get_complementary_data_cache_miss_fetch_success():
    """Sem cache → fetch online + escrita no DB."""
    db_path = tempfile.mktemp(suffix=".duckdb")

    with patch(
        "b3_core.fundamentus.fetch_indicators"
    ) as mock_fetch:
        mock_fetch.return_value = _FAKE_INDICATORS
        result = get_complementary_data("PETR4", db_path=db_path)

    assert "PETROBRAS S.A." in result
    os.unlink(db_path)


def test_get_complementary_data_cache_miss_ignora_db_inexistente(tmp_path):
    """db_path fornecido mas arquivo não existe → faz fetch direto."""
    fake_path = str(tmp_path / "nao_existe.db")
    with patch(
        "b3_core.fundamentus.fetch_indicators"
    ) as mock_fetch:
        mock_fetch.return_value = _FAKE_INDICATORS
        result = get_complementary_data("PETR4", db_path=fake_path)

    assert mock_fetch.called
    assert "PETROBRAS S.A." in result


# --------------------------------------------------------------- fetch-failure
def test_get_complementary_data_fetch_falha_retorna_vazio():
    """Falha na requisição → retorna '' sem propagar exceção."""
    with patch(
        "b3_core.fundamentus.fetch_indicators"
    ) as mock_fetch:
        mock_fetch.side_effect = Exception("HTTP 500")
        result = get_complementary_data("PETR4", db_path=None)

    assert result == ""


def test_get_complementary_data_fetch_retorna_dict_vazio():
    """Fetch retorna {} → tratamento como dado vazio."""
    with patch(
        "b3_core.fundamentus.fetch_indicators"
    ) as mock_fetch:
        mock_fetch.return_value = {}
        result = get_complementary_data("PETR4", db_path=None)

    assert result == ""


# --------------------------------------------------------------- ttl-exceeded
def test_get_complementary_data_cache_expired_fetch_novo():
    """Cache existe mas TTL expirado → faz fetch novo."""
    import duckdb

    path = tempfile.mktemp(suffix=".duckdb")
    con = duckdb.connect(path, read_only=False)
    try:
        con.execute(
            "CREATE TABLE IF NOT EXISTS fundamentus_cache ("
            "ticker TEXT NOT NULL, label TEXT NOT NULL, value TEXT, "
            "source TEXT DEFAULT 'fundamentus.com.br', "
            "fetched_at TIMESTAMP, PRIMARY KEY (ticker, label))"
        )
        ts = datetime.now() - timedelta(hours=25)  # > 24h atrás
        for label in ["P/L", "ROE"]:
            con.execute(
                "INSERT INTO fundamentus_cache (ticker, label, value, fetched_at) VALUES (?, ?, ?, ?)",
                ["PETR4", label, "antigo", ts],
            )
    finally:
        con.close()

    try:
        with patch(
            "b3_core.fundamentus.fetch_indicators"
        ) as mock_fetch:
            mock_fetch.return_value = _FAKE_INDICATORS
            result = get_complementary_data("PETR4", db_path=path)

        assert "PETROBRAS S.A." in result
    finally:
        os.unlink(path)


# --------------------------------------------------------------- _format
def test_format_omite_campos_nulos():
    """Colunas nulas no DataFrame são omitidas do texto."""
    import duckdb

    path = tempfile.mktemp(suffix=".duckdb")
    con = duckdb.connect(path, read_only=False)
    try:
        con.execute(
            "CREATE TABLE IF NOT EXISTS fundamentus_cache ("
            "ticker TEXT NOT NULL, label TEXT NOT NULL, value TEXT, "
            "source TEXT DEFAULT 'fundamentus.com.br', "
            "fetched_at TIMESTAMP, PRIMARY KEY (ticker, label))"
        )
        ts = datetime.now() - timedelta(hours=1)
        # Só labels essenciais + um null-like (vazio)
        for label in ["P/L", "PSR"]:  # PSR will be "" → omitted
            con.execute(
                "INSERT INTO fundamentus_cache (ticker, label, value, fetched_at) VALUES (?, ?, ?, ?)",
                ["XYZ9", label, ("12,34" if label == "P/L" else ""), ts],
            )
    finally:
        con.close()

    try:
        result = get_complementary_data("XYZ9", db_path=path)
        assert "P/L" in result
        assert "PSR" not in result  # vazio → omitido
    finally:
        os.unlink(path)
