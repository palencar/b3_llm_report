"""Testes para src/b3_etl/fundamentus.py e integração em ingest.py."""
import json
import os
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from b3_etl.fundamentus import parse_indicators, _FIELD_MAP, fetch_page
from b3_etl.ingest import _ingest_fundamentus_ticker, run_ingest
from b3_core.config import load_config
from b3_storage.schema import SCHEMA_SQL
from b3_storage.db import connect

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "fundamentus")


def _load_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return f.read()


def test_parse_indicators_extrai_campos_principais():
    html = _load_fixture("PETR4.html")
    result = parse_indicators(html)
    assert "P/L" in result
    assert "P/VP" in result
    assert "ROE" in result
    assert "Div. Yield" in result
    # valores são strings raw (conversão para float ocorre em _ingest_fundamentus_ticker)
    assert result["P/L"] == "8,53"
    assert result["Div. Yield"] == "12,34%"
    for label in _FIELD_MAP:
        assert label in result, f"Campo ausente no parse: {label}"


def test_parse_indicators_html_sem_tabela():
    result = parse_indicators("<html><body>Sem tabelas aqui.</body></html>")
    assert result == {}


def _make_response(content: str, encoding: str = "latin-1") -> MagicMock:
    """Helper: mock compatível com 'with urlopen(...) as resp'."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = content.encode(encoding)
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def test_fetch_page_retorna_html():
    html_content = "<html><body>ok</body></html>"
    with patch("urllib.request.urlopen", return_value=_make_response(html_content)) as mock_open:
        result = fetch_page("PETR4")
    assert "ok" in result
    req = mock_open.call_args[0][0]
    assert "PETR4" in req.full_url
    assert req.get_header("User-agent") == "b3-llm-report/etl"


def _init_db(db_path: str) -> None:
    con = connect(db_path, read_only=False)
    for stmt in SCHEMA_SQL.split(";"):
        stmt = stmt.strip()
        if stmt:
            con.execute(stmt)
    con.close()


def test_ingest_fundamentus_popula_ratios(tmp_path):
    """_ingest_fundamentus_ticker deve gravar ratios, fundamentals e raw_files."""
    db_path = str(tmp_path / "test.duckdb")
    _init_db(db_path)
    html = _load_fixture("PETR4.html")
    config = load_config()
    config = config.__class__(
        **{**config.__dict__, "raw_dir": str(tmp_path / "raw")}
    )
    fetched_at = datetime.now(timezone.utc).replace(tzinfo=None)
    con = connect(db_path, read_only=False)
    # latin-1: fetch_page decodifica a resposta como latin-1; o mock deve
    # codificar da mesma forma para que caracteres acentuados nos nomes de
    # campo (ex.: "Marg. Líquida") sobrevivam à codificação/decodificação.
    with patch("urllib.request.urlopen", return_value=_make_response(html, "latin-1")):
        _ingest_fundamentus_ticker(con, "PETR4", config, fetched_at)
    con.close()

    con = connect(db_path, read_only=True)
    ratio_count = con.execute(
        "SELECT COUNT(*) FROM ratios WHERE ticker = 'PETR4'"
    ).fetchone()[0]
    fund_count = con.execute(
        "SELECT COUNT(*) FROM fundamentals WHERE ticker = 'PETR4' AND source = 'fundamentus.com.br'"
    ).fetchone()[0]
    raw_count = con.execute(
        "SELECT COUNT(*) FROM raw_files WHERE source = 'fundamentus.com.br'"
    ).fetchone()[0]
    con.close()

    assert ratio_count >= 8
    assert fund_count >= 3
    assert raw_count == 1


def test_ingest_fundamentus_falha_silenciosa(tmp_path):
    """Falha de rede no Fundamentus não altera rc=0 nem dados BRAPI já gravados."""
    db_path = str(tmp_path / "test.duckdb")
    _init_db(db_path)
    brapi_fixture_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "brapi", "PETR4.json"
    )
    with open(brapi_fixture_path) as f:
        brapi_data = json.load(f)

    def fake_urlopen(req, timeout=30):
        if "brapi.dev" in req.full_url:
            payload = json.dumps(brapi_data).encode("utf-8")
            mock_resp = MagicMock()
            mock_resp.read.return_value = payload
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp
        raise OSError("simulando falha de rede no Fundamentus")

    config = load_config()
    config = config.__class__(
        **{
            **config.__dict__,
            "db_path": db_path,
            "raw_dir": str(tmp_path / "raw"),
            "snapshot_dir": str(tmp_path / "snapshots"),
        }
    )
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        rc = run_ingest(["PETR4"], config, ["financialData"], write_snapshot=False)

    assert rc == 0
    con = connect(db_path, read_only=True)
    companies = con.execute(
        "SELECT ticker FROM companies WHERE ticker = 'PETR4'"
    ).fetchall()
    con.close()
    assert len(companies) == 1
