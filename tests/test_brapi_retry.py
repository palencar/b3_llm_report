import pytest
from unittest.mock import patch, MagicMock, call
import json

from b3_etl.brapi import fetch_quote, BrapiError


def _make_valid_response(ticker="PETR4"):
    body = json.dumps({"results": [{"shortName": ticker}]}).encode()
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = body
    return mock_resp


def test_retry_esgota_3_tentativas_e_levanta_brapi_error():
    with patch("b3_etl.brapi.urllib.request.urlopen", side_effect=OSError("timeout")) as mock_open, \
         patch("b3_etl.brapi.time.sleep") as mock_sleep:
        with pytest.raises(BrapiError):
            fetch_quote("PETR4", [], "https://brapi.dev/api", "")
        assert mock_open.call_count == 3
        assert mock_sleep.call_count == 2  # sleep entre tentativas, não após a última


def test_retry_sucede_na_segunda_tentativa():
    valid = _make_valid_response()
    with patch("b3_etl.brapi.urllib.request.urlopen",
               side_effect=[OSError("timeout"), valid]) as mock_open, \
         patch("b3_etl.brapi.time.sleep"):
        result = fetch_quote("PETR4", [], "https://brapi.dev/api", "")
    assert mock_open.call_count == 2
    assert "results" in result


def test_schema_invalido_nao_faz_retry():
    body = json.dumps({"erro": "not found"}).encode()
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = body
    with patch("b3_etl.brapi.urllib.request.urlopen", return_value=mock_resp) as mock_open, \
         patch("b3_etl.brapi.time.sleep") as mock_sleep:
        with pytest.raises(BrapiError):
            fetch_quote("PETR4", [], "https://brapi.dev/api", "")
    assert mock_open.call_count == 1  # sem retry
    mock_sleep.assert_not_called()
