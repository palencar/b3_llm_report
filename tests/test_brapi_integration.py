"""
Testes de integração usando fixtures JSON pré-gravadas da BRAPI.
Não fazem chamadas de rede — patch em urllib.request.urlopen.
"""
import json
import os
from io import BytesIO
from unittest.mock import patch, MagicMock

import pytest

from b3_etl.brapi import fetch_quote
from b3_etl.ingest import run_ingest, _extract_statement_records
from b3_core.config import load_config
from b3_storage.schema import SCHEMA_SQL
from b3_storage.db import connect

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "brapi")
TICKERS = ["PETR4", "ITUB4", "VALE3"]


def _load_fixture(ticker: str) -> dict:
    with open(os.path.join(FIXTURES_DIR, f"{ticker}.json"), encoding="utf-8") as f:
        return json.load(f)


def _make_urlopen_mock(data: dict):
    """Retorna mock compatível com 'with urlopen(...) as resp'."""
    payload = json.dumps(data).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.read.return_value = payload
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


# ---------------------------------------------------------------------------
# fetch_quote
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ticker", TICKERS)
def test_fetch_quote_returns_results(ticker):
    """fetch_quote deve retornar dict com chave 'results' para cada ticker."""
    fixture = _load_fixture(ticker)
    with patch("urllib.request.urlopen", return_value=_make_urlopen_mock(fixture)):
        result = fetch_quote(ticker, ["financialData"], "https://brapi.dev/api", "")
    assert isinstance(result, dict)
    assert "results" in result
    assert len(result["results"]) >= 1
    assert result["results"][0]["symbol"] == ticker


@pytest.mark.parametrize("ticker", TICKERS)
def test_fetch_quote_financial_fields_present(ticker):
    """financialData deve conter revenue e totalDebt no fixture."""
    fixture = _load_fixture(ticker)
    with patch("urllib.request.urlopen", return_value=_make_urlopen_mock(fixture)):
        result = fetch_quote(ticker, ["financialData"], "https://brapi.dev/api", "")
    fd = result["results"][0].get("financialData", {})
    assert "revenue" in fd
    assert "totalDebt" in fd


# ---------------------------------------------------------------------------
# _extract_statement_records
# ---------------------------------------------------------------------------

def test_extract_income_statement_petr4():
    """Deve extrair 2 períodos do incomeStatementHistory do PETR4."""
    fixture = _load_fixture("PETR4")
    from datetime import datetime, timezone
    fetched_at = datetime.now(timezone.utc).replace(tzinfo=None)
    records = _extract_statement_records(
        "PETR4",
        fixture["results"][0]["incomeStatementHistory"],
        "income",
        "BRL",
        "brapi.dev",
        fetched_at,
    )
    periods = {str(r["period"]) for r in records}
    assert "2023-12-31" in periods
    assert "2022-12-31" in periods
    keys = {r["key"] for r in records}
    assert "totalRevenue" in keys
    assert "netIncome" in keys


def test_extract_balance_sheet_itub4():
    """Deve extrair totalAssets e totalLiabilities do balanço do ITUB4."""
    fixture = _load_fixture("ITUB4")
    from datetime import datetime, timezone
    fetched_at = datetime.now(timezone.utc).replace(tzinfo=None)
    records = _extract_statement_records(
        "ITUB4",
        fixture["results"][0]["balanceSheetHistory"],
        "balance",
        "BRL",
        "brapi.dev",
        fetched_at,
    )
    keys = {r["key"] for r in records}
    assert "totalAssets" in keys
    assert "totalStockholderEquity" in keys


# ---------------------------------------------------------------------------
# run_ingest — modo skip_db (sem banco)
# ---------------------------------------------------------------------------

def test_run_ingest_skip_db_writes_raw_file(tmp_path):
    """run_ingest --skip-db deve gravar arquivo raw JSON sem acessar DuckDB."""
    fixture = _load_fixture("PETR4")
    config = load_config()
    config = config.__class__(
        **{**config.__dict__, "raw_dir": str(tmp_path / "raw")}
    )
    with patch("urllib.request.urlopen", return_value=_make_urlopen_mock(fixture)):
        rc = run_ingest(["PETR4"], config, ["financialData"], write_snapshot=False, skip_db=True)
    assert rc == 0
    raw_files = list((tmp_path / "raw" / "brapi" / "PETR4").iterdir())
    assert len(raw_files) == 1
    saved = json.loads(raw_files[0].read_text())
    assert saved["results"][0]["symbol"] == "PETR4"


# ---------------------------------------------------------------------------
# run_ingest — com DuckDB real (tmp)
# ---------------------------------------------------------------------------

def _init_db(db_path: str) -> None:
    con = connect(db_path, read_only=False)
    for stmt in SCHEMA_SQL.split(";"):
        stmt = stmt.strip()
        if stmt:
            con.execute(stmt)
    con.close()


def test_run_ingest_writes_to_db(tmp_path):
    """run_ingest deve popular companies, fundamentals e prices no DuckDB."""
    db_path = str(tmp_path / "test.duckdb")
    _init_db(db_path)
    fixture = _load_fixture("PETR4")
    config = load_config()
    config = config.__class__(
        **{
            **config.__dict__,
            "db_path": db_path,
            "raw_dir": str(tmp_path / "raw"),
            "snapshot_dir": str(tmp_path / "snapshots"),
        }
    )
    with patch("urllib.request.urlopen", return_value=_make_urlopen_mock(fixture)):
        rc = run_ingest(["PETR4"], config, ["financialData", "balanceSheetHistory", "incomeStatementHistory"], write_snapshot=False)
    assert rc == 0
    con = connect(db_path, read_only=True)
    rows = con.execute("SELECT ticker FROM companies WHERE ticker = 'PETR4'").fetchall()
    assert len(rows) == 1
    fund_count = con.execute("SELECT COUNT(*) FROM fundamentals WHERE ticker = 'PETR4'").fetchone()[0]
    assert fund_count > 0
    price_count = con.execute("SELECT COUNT(*) FROM prices WHERE ticker = 'PETR4'").fetchone()[0]
    assert price_count == 1
    con.close()


def test_run_ingest_three_tickers(tmp_path):
    """run_ingest deve processar PETR4, ITUB4 e VALE3 sem erros."""
    db_path = str(tmp_path / "test.duckdb")
    _init_db(db_path)
    config = load_config()
    config = config.__class__(
        **{
            **config.__dict__,
            "db_path": db_path,
            "raw_dir": str(tmp_path / "raw"),
            "snapshot_dir": str(tmp_path / "snapshots"),
        }
    )

    fixtures = {t: _load_fixture(t) for t in TICKERS}
    call_count = {"n": 0}

    def fake_urlopen(req, timeout=30):
        ticker = req.full_url.split("/quote/")[1].split("?")[0]
        call_count["n"] += 1
        return _make_urlopen_mock(fixtures[ticker])

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        rc = run_ingest(TICKERS, config, ["financialData"], write_snapshot=False)
    assert rc == 0
    assert call_count["n"] == 3
    con = connect(db_path, read_only=True)
    count = con.execute("SELECT COUNT(DISTINCT ticker) FROM companies").fetchone()[0]
    assert count == 3
    con.close()
