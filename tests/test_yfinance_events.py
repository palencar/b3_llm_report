import json
from unittest.mock import Mock, PropertyMock, patch

import pytest

from b3_report.sources.yfinance import EVENT_SOURCE_VERSION, extract_yfinance_info, format_yfinance_data
from b3_report.snapshot import build_snapshot


def extract(info):
    stock = Mock(info={"symbol": "WEGE3.SA", **info}, recommendations=None)
    type(stock).calendar = PropertyMock(side_effect=AssertionError("Nao consultar calendario"))
    stock.get_earnings_dates.side_effect = AssertionError("Nao consultar earnings_dates")
    with patch("b3_report.sources.yfinance.yf.Ticker", return_value=stock) as ticker:
        data = json.loads(extract_yfinance_info("WEGE3.SA"))
    ticker.assert_called_once_with("WEGE3.SA")
    stock.get_earnings_dates.assert_not_called()
    return data


def test_preserva_datas_e_intervalo_sem_requisicao_adicional():
    raw = {"earningsTimestamp": 1792598400, "earningsTimestampStart": 1792598400,
           "earningsTimestampEnd": 1792684800, "isEarningsDateEstimate": True,
           "exchangeTimezoneName": "America/Sao_Paulo"}
    data = extract(raw)
    event = data["Event Metadata"]
    assert event["raw_fields"] == raw
    assert event["certainty"] == "estimativa"
    assert event["status"] == "datas_reportadas"
    assert event["timestamps_utc"]["earningsTimestamp"].endswith("+00:00")
    assert event["timestamps_utc"]["earningsTimestampStart"] != event["timestamps_utc"]["earningsTimestampEnd"]
    assert event["version"] == EVENT_SOURCE_VERSION
    assert "earningsTimestampStart" in format_yfinance_data(data)
    snapshot = build_snapshot(ticker="WEGE3", analysis_date="2026-10-21", yfinance_data=data,
        fundamentus_text="", cvm_rows=[])
    assert snapshot["source_data"]["yfinance"]["Event Metadata"] == event
    assert "event_context" not in snapshot  # Nao fabrica calendario confirmado.
    assert snapshot["risk_evidence"] == {}


def test_ausencia_e_limitacao_da_resposta_nao_calendario_vazio_confirmado():
    event = extract({})["Event Metadata"]
    assert event["status"] == "datas_nao_fornecidas_em_info"
    assert event["raw_fields"] == event["timestamps_utc"] == {}
    assert event["certainty"] == "desconhecida"


def test_flag_falsa_nao_e_confirmacao_de_divulgacao():
    event = extract({"isEarningsDateEstimate": False})["Event Metadata"]
    assert event["certainty"] == "nao_marcada_como_estimativa"
    assert event["status"] == "datas_nao_fornecidas_em_info"
    assert "Data passada nao confirma" in event["limitations"]


@pytest.mark.parametrize("value", [True, "2026-10-21", None, 10**30])
def test_nao_inventa_timestamp_para_valor_invalido(value):
    event = extract({"earningsTimestamp": value})["Event Metadata"]
    assert event["raw_fields"]["earningsTimestamp"] == value
    assert event["timestamps_utc"] == {}


def test_timestamp_de_earnings_call_nao_e_rotulado_como_resultado():
    event = extract({"earningsCallTimestamp": 1792598400})["Event Metadata"]
    assert list(event["timestamps_utc"]) == ["earningsCallTimestamp"]
