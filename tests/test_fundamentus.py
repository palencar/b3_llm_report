"""Testes para src/b3_etl/fundamentus.py e integração em ingest.py."""
import os
from unittest.mock import patch, MagicMock

from b3_etl.fundamentus import parse_indicators, _FIELD_MAP, fetch_page

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
    assert "Div.Yield" in result
    # valores são strings raw (conversão para float ocorre em _ingest_fundamentus_ticker)
    assert result["P/L"] == "8,53"
    assert result["Div.Yield"] == "12,34%"
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
