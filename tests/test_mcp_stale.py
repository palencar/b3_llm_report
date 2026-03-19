# IMPORTANTE: conftest.py adiciona src/ ao sys.path.
# Todos os imports e patches usam b3_mcp.app (sem prefixo src.)
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta
from fastapi.testclient import TestClient

from b3_mcp.app import app


def _auth_headers():
    return {"Authorization": "Bearer test-token"}


@pytest.fixture(autouse=True)
def set_auth_token(monkeypatch):
    monkeypatch.setenv("AUTH_TOKEN", "test-token")


def _fake_meta(last_update):
    return {
        "name": "Petrobras",
        "sector": "Energy",
        "industry": "Oil",
        "last_update": last_update,
        "last_update_str": last_update.isoformat() if last_update else None,
        "source": "brapi.dev",
    }


def _fake_con():
    con = MagicMock()
    con.execute.return_value.fetchone.return_value = [None]
    con.execute.return_value.fetchall.return_value = []
    return con


def test_stale_false_quando_last_update_recente():
    recent = datetime.utcnow() - timedelta(hours=1)
    with patch("b3_mcp.app.os.path.exists", return_value=True), \
         patch("b3_mcp.app.connect", return_value=_fake_con()), \
         patch("b3_mcp.app.missing_tables", return_value=[]), \
         patch("b3_mcp.app._company_metadata", return_value=_fake_meta(recent)), \
         patch("b3_mcp.app._latest_period", return_value=None), \
         patch("b3_mcp.app._latest_price", return_value=None), \
         patch("b3_mcp.app.config") as mock_config:
        mock_config.auth_token = "test-token"
        mock_config.fund_ttl = 86400
        mock_config.price_ttl = 900
        mock_config.db_path = "/fake/path.duckdb"
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/v1/fundamentals/PETR4", headers=_auth_headers())

    assert response.status_code == 200
    assert response.json()["metadata"]["stale"] is False


def test_stale_true_quando_last_update_antigo():
    old = datetime.utcnow() - timedelta(hours=30)
    with patch("b3_mcp.app.os.path.exists", return_value=True), \
         patch("b3_mcp.app.connect", return_value=_fake_con()), \
         patch("b3_mcp.app.missing_tables", return_value=[]), \
         patch("b3_mcp.app._company_metadata", return_value=_fake_meta(old)), \
         patch("b3_mcp.app._latest_period", return_value=None), \
         patch("b3_mcp.app._latest_price", return_value=None), \
         patch("b3_mcp.app.config") as mock_config:
        mock_config.auth_token = "test-token"
        mock_config.fund_ttl = 86400
        mock_config.price_ttl = 900
        mock_config.db_path = "/fake/path.duckdb"
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/v1/fundamentals/PETR4", headers=_auth_headers())

    assert response.status_code == 200
    assert response.json()["metadata"]["stale"] is True


def test_stale_true_quando_nenhum_dado():
    with patch("b3_mcp.app.os.path.exists", return_value=True), \
         patch("b3_mcp.app.connect", return_value=_fake_con()), \
         patch("b3_mcp.app.missing_tables", return_value=[]), \
         patch("b3_mcp.app._company_metadata", return_value=_fake_meta(None)), \
         patch("b3_mcp.app._latest_period", return_value=None), \
         patch("b3_mcp.app._latest_price", return_value=None), \
         patch("b3_mcp.app.config") as mock_config:
        mock_config.auth_token = "test-token"
        mock_config.fund_ttl = 86400
        mock_config.price_ttl = 900
        mock_config.db_path = "/fake/path.duckdb"
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/v1/fundamentals/PETR4", headers=_auth_headers())

    assert response.status_code == 200
    assert response.json()["metadata"]["stale"] is True
