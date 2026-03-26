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


def test_load_statements_tipos_vazio_retorna_dict_vazio(tmp_path):
    con = _init_con(str(tmp_path / "t.duckdb"))
    _seed_data(con)
    result = _load_statements(con, "PETR4", 2022, 2024, [])
    assert result == {}
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


# ---------------------------------------------------------------------------
# Fixtures de rota
# ---------------------------------------------------------------------------

def _auth():
    return {"Authorization": "Bearer test-token"}


@pytest.fixture(autouse=True)
def set_auth_token(monkeypatch):
    monkeypatch.setenv("AUTH_TOKEN", "test-token")


def _mock_config():
    m = MagicMock()
    m.auth_token = "test-token"
    m.fund_ttl = 86400
    m.db_path = "/fake/path.duckdb"
    return m


def _mock_con(max_year=2024):
    con = MagicMock()
    con.execute.return_value.fetchone.return_value = [max_year]
    return con


_GROUPED_STUB = {
    "BPA": [{"period": "2024-12-31", "account_code": "1",
             "account_name": "Ativo Total", "value": 1e9,
             "currency": "REAL", "source": "cvm_dfp"}],
    "BPP": [], "DRE": [], "DFC_MI": [], "DFC_MD": [],
}

# ---------------------------------------------------------------------------
# Testes de rota
# ---------------------------------------------------------------------------

def test_statements_retorna_dados_agrupados():
    from b3_mcp.cache import TTLCache
    mock_con = _mock_con()
    with patch("b3_mcp.app.os.path.exists", return_value=True), \
         patch("b3_mcp.app.connect", return_value=mock_con), \
         patch("b3_mcp.app.missing_tables", return_value=[]), \
         patch("b3_mcp.app._find_ticker_cnpj", return_value="33000167000101"), \
         patch("b3_mcp.app._load_statements", return_value=_GROUPED_STUB), \
         patch("b3_mcp.app._statements_stale", return_value=False), \
         patch("b3_mcp.app.cache", TTLCache()), \
         patch("b3_mcp.app.config", _mock_config()):
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/v1/statements/PETR4", headers=_auth())

    assert response.status_code == 200
    data = response.json()
    assert data["ticker"] == "PETR4"
    assert "BPA" in data["statements"]
    assert len(data["statements"]["BPA"]) == 1
    assert data["statements"]["BPA"][0]["account_name"] == "Ativo Total"
    assert data["metadata"]["cnpj"] == "33000167000101"
    assert data["metadata"]["stale"] is False
    assert "2024-12-31" in data["metadata"]["periods"]


def test_statements_ticker_nao_encontrado():
    from b3_mcp.cache import TTLCache
    mock_con = _mock_con()
    with patch("b3_mcp.app.os.path.exists", return_value=True), \
         patch("b3_mcp.app.connect", return_value=mock_con), \
         patch("b3_mcp.app.missing_tables", return_value=[]), \
         patch("b3_mcp.app._find_ticker_cnpj", return_value=None), \
         patch("b3_mcp.app.cache", TTLCache()), \
         patch("b3_mcp.app.config", _mock_config()):
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/v1/statements/XXXX3", headers=_auth())

    assert response.status_code == 404


def test_statements_sem_dados_cvm_retorna_vazio():
    """Ticker existe em ticker_map mas não há linhas em cvm_statements."""
    from b3_mcp.cache import TTLCache
    mock_con = MagicMock()
    # max_year query retorna None (sem dados CVM)
    mock_con.execute.return_value.fetchone.return_value = [None]
    with patch("b3_mcp.app.os.path.exists", return_value=True), \
         patch("b3_mcp.app.connect", return_value=mock_con), \
         patch("b3_mcp.app.missing_tables", return_value=[]), \
         patch("b3_mcp.app._find_ticker_cnpj", return_value="33000167000101"), \
         patch("b3_mcp.app._statements_stale", return_value=True), \
         patch("b3_mcp.app.cache", TTLCache()), \
         patch("b3_mcp.app.config", _mock_config()):
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/v1/statements/PETR4", headers=_auth())

    assert response.status_code == 200
    data = response.json()
    assert data["statements"]["BPA"] == []
    assert data["metadata"]["periods"] == []
    assert data["metadata"]["stale"] is True


def test_statements_filtro_types():
    """?types=BPA retorna apenas BPA na resposta."""
    from b3_mcp.cache import TTLCache
    grouped_bpa_only = {"BPA": [{"period": "2024-12-31", "account_code": "1",
                                  "account_name": "Ativo Total", "value": 1e9,
                                  "currency": "REAL", "source": "cvm_dfp"}]}
    mock_con = _mock_con()
    with patch("b3_mcp.app.os.path.exists", return_value=True), \
         patch("b3_mcp.app.connect", return_value=mock_con), \
         patch("b3_mcp.app.missing_tables", return_value=[]), \
         patch("b3_mcp.app._find_ticker_cnpj", return_value="33000167000101"), \
         patch("b3_mcp.app._load_statements", return_value=grouped_bpa_only) as mock_load, \
         patch("b3_mcp.app._statements_stale", return_value=False), \
         patch("b3_mcp.app.cache", TTLCache()), \
         patch("b3_mcp.app.config", _mock_config()):
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/v1/statements/PETR4?types=BPA", headers=_auth())

    assert response.status_code == 200
    # Verifica que _load_statements foi chamado com types=["BPA"]
    call_args = mock_load.call_args
    assert call_args[0][4] == ["BPA"]   # 5º argumento posicional: types


def test_statements_filtro_periodo():
    """?from=2022&to=2023 passa from_year=2022, to_year=2023 para _load_statements."""
    from b3_mcp.cache import TTLCache
    grouped_stub = {"BPA": [], "BPP": [], "DRE": [], "DFC_MI": [], "DFC_MD": []}
    mock_con = _mock_con()
    with patch("b3_mcp.app.os.path.exists", return_value=True), \
         patch("b3_mcp.app.connect", return_value=mock_con), \
         patch("b3_mcp.app.missing_tables", return_value=[]), \
         patch("b3_mcp.app._find_ticker_cnpj", return_value="33000167000101"), \
         patch("b3_mcp.app._load_statements", return_value=grouped_stub) as mock_load, \
         patch("b3_mcp.app._statements_stale", return_value=False), \
         patch("b3_mcp.app.cache", TTLCache()), \
         patch("b3_mcp.app.config", _mock_config()):
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/v1/statements/PETR4?from=2022&to=2023", headers=_auth())

    assert response.status_code == 200
    call_args = mock_load.call_args
    assert call_args[0][2] == 2022   # from_year
    assert call_args[0][3] == 2023   # to_year


def test_statements_ano_invalido_retorna_400():
    """?from=abc ou ?to=xyz retornam 400."""
    from b3_mcp.cache import TTLCache
    mock_con = _mock_con()
    with patch("b3_mcp.app.os.path.exists", return_value=True), \
         patch("b3_mcp.app.connect", return_value=mock_con), \
         patch("b3_mcp.app.missing_tables", return_value=[]), \
         patch("b3_mcp.app._find_ticker_cnpj", return_value="33000167000101"), \
         patch("b3_mcp.app.cache", TTLCache()), \
         patch("b3_mcp.app.config", _mock_config()):
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/v1/statements/PETR4?from=abc", headers=_auth())

    assert response.status_code == 400


def test_statements_types_invalidos_usa_default():
    """?types=INVALID silently falls back to default types."""
    from b3_mcp.cache import TTLCache
    grouped_stub = {"BPA": [], "BPP": [], "DRE": [], "DFC_MI": [], "DFC_MD": []}
    mock_con = _mock_con()
    with patch("b3_mcp.app.os.path.exists", return_value=True), \
         patch("b3_mcp.app.connect", return_value=mock_con), \
         patch("b3_mcp.app.missing_tables", return_value=[]), \
         patch("b3_mcp.app._find_ticker_cnpj", return_value="33000167000101"), \
         patch("b3_mcp.app._load_statements", return_value=grouped_stub) as mock_load, \
         patch("b3_mcp.app._statements_stale", return_value=False), \
         patch("b3_mcp.app.cache", TTLCache()), \
         patch("b3_mcp.app.config", _mock_config()):
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/v1/statements/PETR4?types=INVALID", headers=_auth())

    assert response.status_code == 200
    # Should fall back to 5 default types
    call_args = mock_load.call_args
    assert call_args[0][4] == ["BPA", "BPP", "DRE", "DFC_MI", "DFC_MD"]


def test_statements_cache_evita_segunda_query():
    """Segunda chamada idêntica usa cache e não invoca _load_statements."""
    from b3_mcp.cache import TTLCache
    grouped_stub = {"BPA": [], "BPP": [], "DRE": [], "DFC_MI": [], "DFC_MD": []}
    shared_cache = TTLCache()
    mock_con = _mock_con()
    with patch("b3_mcp.app.os.path.exists", return_value=True), \
         patch("b3_mcp.app.connect", return_value=mock_con), \
         patch("b3_mcp.app.missing_tables", return_value=[]), \
         patch("b3_mcp.app._find_ticker_cnpj", return_value="33000167000101"), \
         patch("b3_mcp.app._load_statements", return_value=grouped_stub) as mock_load, \
         patch("b3_mcp.app._statements_stale", return_value=False), \
         patch("b3_mcp.app.cache", shared_cache), \
         patch("b3_mcp.app.config", _mock_config()):
        client = TestClient(app, raise_server_exceptions=False)
        client.get("/v1/statements/PETR4?from=2022&to=2024", headers=_auth())
        client.get("/v1/statements/PETR4?from=2022&to=2024", headers=_auth())

    assert mock_load.call_count == 1   # apenas 1 chamada, a segunda usou cache
