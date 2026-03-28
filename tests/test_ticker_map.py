"""Testes para src/b3_etl/ticker_map.py."""
import os
from unittest.mock import patch

import pytest

from b3_etl.ticker_map import parse_b3_results

# ---------------------------------------------------------------------------
# Fixtures em memória
# ---------------------------------------------------------------------------

_FAKE_RESULTS = [
    {"issuingCompany": "PETR4", "cnpj": "33000167000101", "companyName": "PETROBRAS S.A."},
    {"issuingCompany": "PETR3", "cnpj": "33000167000101", "companyName": "PETROBRAS S.A."},
    {"issuingCompany": "",      "cnpj": "99999999000100", "companyName": "SEM TICKER"},
    {"issuingCompany": "ITUB4", "cnpj": "",               "companyName": "SEM CNPJ"},
    {"issuingCompany": "VALE3", "cnpj": "33.592.510/0001-03", "companyName": "VALE S.A."},
]

_FAKE_PAGE_1 = {
    "page": {"pageNumber": 1, "pageSize": 4, "totalRecords": 5, "totalPages": 2},
    "results": [
        {"issuingCompany": "PETR4", "cnpj": "33000167000101", "companyName": "PETROBRAS S.A."},
        {"issuingCompany": "PETR3", "cnpj": "33000167000101", "companyName": "PETROBRAS S.A."},
        {"issuingCompany": "",      "cnpj": "99999999000100", "companyName": "SEM TICKER"},
        {"issuingCompany": "ITUB4", "cnpj": "",               "companyName": "SEM CNPJ"},
    ],
}

_FAKE_PAGE_2 = {
    "page": {"pageNumber": 2, "pageSize": 4, "totalRecords": 5, "totalPages": 2},
    "results": [
        {"issuingCompany": "VALE3", "cnpj": "33592510000103", "companyName": "VALE S.A."},
    ],
}


def _fake_fetch(page: int, page_size: int = 120, timeout: int = 30) -> dict:
    return _FAKE_PAGE_1 if page == 1 else _FAKE_PAGE_2


def _init_db(db_path: str) -> None:
    from b3_storage.schema import SCHEMA_SQL
    from b3_storage.db import connect
    con = connect(db_path, read_only=False)
    for stmt in SCHEMA_SQL.split(";"):
        stmt = stmt.strip()
        if stmt:
            con.execute(stmt)
    con.close()


def _make_config(tmp_path: str):
    from b3_core.config import load_config
    config = load_config()
    db_path = os.path.join(tmp_path, "test.duckdb")
    _init_db(db_path)
    return config.__class__(
        **{**config.__dict__, "db_path": db_path}
    )


# ---------------------------------------------------------------------------
# Task 1: parse_b3_results
# ---------------------------------------------------------------------------

def test_parse_b3_results():
    result = parse_b3_results(_FAKE_RESULTS)
    # PETR4, PETR3, VALE3 válidos; SEM TICKER (ticker vazio) e SEM CNPJ (cnpj vazio) ignorados
    assert len(result) == 3
    tickers = {r["ticker"] for r in result}
    assert "PETR4" in tickers
    assert "PETR3" in tickers
    assert "VALE3" in tickers
    # CNPJ normalizado: apenas dígitos
    petr4 = next(r for r in result if r["ticker"] == "PETR4")
    assert petr4["cnpj"] == "33000167000101"
    assert petr4["name"] == "PETROBRAS S.A."
    # CNPJ com pontuação também é normalizado
    vale = next(r for r in result if r["ticker"] == "VALE3")
    assert vale["cnpj"] == "33592510000103"


# ---------------------------------------------------------------------------
# Task 2: fetch_b3_page + run_build_ticker_map
# ---------------------------------------------------------------------------

def test_paginacao_usa_page_totalPages(tmp_path):
    """run_build_ticker_map deve ler totalPages de data['page']['totalPages']."""
    from b3_etl.ticker_map import run_build_ticker_map
    from b3_storage.db import connect

    config = _make_config(str(tmp_path))
    pages_fetched = []

    def _fake(page: int, page_size: int = 120, timeout: int = 30) -> dict:
        pages_fetched.append(page)
        if page == 1:
            return {
                "page": {"pageNumber": 1, "pageSize": 2, "totalRecords": 3, "totalPages": 2},
                "results": [
                    {"issuingCompany": "PETR4", "cnpj": "33000167000101", "companyName": "PETROBRAS S.A."},
                ],
            }
        return {
            "page": {"pageNumber": 2, "pageSize": 2, "totalRecords": 3, "totalPages": 2},
            "results": [
                {"issuingCompany": "VALE3", "cnpj": "33592510000103", "companyName": "VALE S.A."},
            ],
        }

    with patch("b3_etl.ticker_map.fetch_b3_page", side_effect=_fake):
        rc = run_build_ticker_map(config=config)

    assert rc == 0
    assert pages_fetched == [1, 2], f"Expected [1, 2], got {pages_fetched}"

    con = connect(config.db_path, read_only=True)
    count = con.execute("SELECT COUNT(*) FROM ticker_map").fetchone()[0]
    con.close()
    assert count == 2


def test_run_build_ticker_map_popula_tabela(tmp_path):
    """run_build_ticker_map deve gravar ticker_map com registros corretos."""
    from b3_etl.ticker_map import run_build_ticker_map
    from b3_storage.db import connect

    config = _make_config(str(tmp_path))
    with patch("b3_etl.ticker_map.fetch_b3_page", side_effect=_fake_fetch):
        rc = run_build_ticker_map(config=config)
    assert rc == 0

    con = connect(config.db_path, read_only=True)
    count = con.execute("SELECT COUNT(*) FROM ticker_map").fetchone()[0]
    tickers = {r[0] for r in con.execute("SELECT ticker FROM ticker_map").fetchall()}
    con.close()

    # PETR4, PETR3 (página 1) + VALE3 (página 2) = 3; SEM TICKER e SEM CNPJ ignorados
    assert count == 3
    assert "PETR4" in tickers
    assert "PETR3" in tickers
    assert "VALE3" in tickers


def test_run_build_ticker_map_falha_rede(tmp_path):
    """OSError na página 2 → rc=0, dados da página 1 gravados."""
    from b3_etl.ticker_map import run_build_ticker_map
    from b3_storage.db import connect

    config = _make_config(str(tmp_path))

    def _fake_page2_fails(page: int, page_size: int = 120, timeout: int = 30) -> dict:
        if page == 1:
            return _FAKE_PAGE_1  # totalPages=2
        raise OSError("timeout")

    with patch("b3_etl.ticker_map.fetch_b3_page", side_effect=_fake_page2_fails):
        rc = run_build_ticker_map(config=config)
    assert rc == 0

    con = connect(config.db_path, read_only=True)
    count = con.execute("SELECT COUNT(*) FROM ticker_map").fetchone()[0]
    tickers = {r[0] for r in con.execute("SELECT ticker FROM ticker_map").fetchall()}
    con.close()

    # Apenas PETR4 e PETR3 (página 1); VALE3 não gravado (página 2 falhou)
    assert count == 2
    assert "PETR4" in tickers
    assert "PETR3" in tickers


def test_run_build_ticker_map_idempotente(tmp_path):
    """Segunda execução produz o mesmo resultado sem duplicatas."""
    from b3_etl.ticker_map import run_build_ticker_map
    from b3_storage.db import connect

    config = _make_config(str(tmp_path))
    with patch("b3_etl.ticker_map.fetch_b3_page", side_effect=_fake_fetch):
        run_build_ticker_map(config=config)
        run_build_ticker_map(config=config)

    con = connect(config.db_path, read_only=True)
    count = con.execute("SELECT COUNT(*) FROM ticker_map").fetchone()[0]
    con.close()
    assert count == 3  # mesmo resultado, sem duplicatas
