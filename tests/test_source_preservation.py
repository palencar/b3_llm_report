from copy import deepcopy
from datetime import datetime, timedelta
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import duckdb
import pytest

from b3_report.snapshot import NORMALIZATION_POLICY, build_snapshot, collect_snapshot, snapshot_id
from b3_report.sources.fundamentus import get_complementary_data, get_complementary_payload
from b3_report.sources.yfinance import extract_yfinance_info
from b3_report.rubric import check_data_readiness
from b3_storage.fundamentus import save_cache, load_cache


def build(payload=None, yfinance=None):
    return build_snapshot(ticker="FIIB11", analysis_date="2026-10-15",
                                  yfinance_data=yfinance or {}, fundamentus_text="Texto simulado.", cvm_rows=[],
                                  fundamentus_payload=payload)


def fund(value="0,73", **extra):
    return {"text": "Texto simulado.", "indicators": {"P/VP": value, "Data últ cot": "15/10/2026", **extra},
            "fetched_at": "2026-10-15T10:00:00"}


def test_payload_preserva_campos_fora_do_texto_sem_segunda_coleta():
    raw = {"P/VP": "0,73", "Cres. Rec (5a)": "4,5%", "Campo adicional": "Valor original"}
    with patch("b3_core.fundamentus.fetch_indicators", return_value=raw) as fetch:
        payload = get_complementary_payload("FIIB11")
    fetch.assert_called_once_with("FIIB11")
    assert payload["indicators"] == raw
    assert "Campo adicional" not in payload["text"]
    assert datetime.fromisoformat(payload["fetched_at"])


def test_payload_usa_cache_e_preserva_data_original(tmp_path):
    path = str(tmp_path / "cache.duckdb")
    fetched = datetime.now() - timedelta(minutes=5)
    raw = {"P/VP": "0,73", "Campo adicional": "Preservado"}
    save_cache(path, "FIIB11", raw, fetched)
    with patch("b3_core.fundamentus.fetch_indicators", side_effect=AssertionError("Nao usar rede.")):
        payload = get_complementary_payload("FIIB11", db_path=path)
    assert payload["indicators"] == raw
    assert payload["fetched_at"] == fetched.isoformat()


def test_interface_textual_legada_preservada():
    with patch("b3_core.fundamentus.fetch_indicators", return_value={"P/VP": "0,73"}):
        assert "0,73" in get_complementary_data("FIIB11")


def test_sem_fonte_nao_inventa_payload():
    with patch("b3_core.fundamentus.fetch_indicators", side_effect=RuntimeError("Falha simulada.")):
        assert get_complementary_payload("FIIB11") == {"text": "", "indicators": {}, "fetched_at": None}


def test_snapshot_estruturado_valuation_fonte_e_datas(caplog):
    payload = fund(**{"Cres. Rec (5a)": "4,5%"})
    before = deepcopy(payload)
    snapshot = build(payload)
    assert snapshot["normalization_policy"] == NORMALIZATION_POLICY
    assert snapshot["source_data"]["fundamentus"] == payload
    assert snapshot["evidence"]["valuation"] == {"value": {"Price to Book": 0.73}, "source": "fundamentus",
        "as_of": "2026-10-15", "available_at": "2026-10-15", "conflict": False}
    # Crescimento de cinco anos nao vira silenciosamente crescimento de outro horizonte.
    assert snapshot["evidence"]["growth"]["value"] == {}
    assert payload == before


def test_yfinance_primario_nao_e_sobrescrito_ou_mesclado():
    snapshot = build(fund(**{"P/L": "8,5"}), {"Financial Metrics": {"Price to Book": 0.8}})
    assert snapshot["evidence"]["valuation"]["source"] == "yfinance"
    assert snapshot["evidence"]["valuation"]["value"] == {"Price to Book": 0.8}


@pytest.mark.parametrize("value", ["-", "N/A", "NaN", "0.73", "1e3", "", "9" * 400])
def test_valor_invalido_nao_libera_gate(value):
    assert build(fund(value))["evidence"]["valuation"]["value"] == {}


def test_datas_ausentes_nao_sao_inventadas():
    payload = fund()
    payload["indicators"].pop("Data últ cot")
    payload["fetched_at"] = None
    value = build(payload)["evidence"]["valuation"]
    assert value["as_of"] is value["available_at"] is None
    evidence = {"valuation": value}
    readiness = check_data_readiness(evidence, analysis_date="2026-10-15", horizon="curto")
    assert "valuation: data" in readiness["reason"]


@pytest.mark.parametrize("quoted, expected", [
    ("01/10/2026", "valuation: dado excede limite"),
    ("16/10/2026", "valuation: datas futuras"),
])
def test_fundamentus_nao_contorna_validacao_de_atualidade(quoted, expected):
    snapshot = build(fund(**{"Data últ cot": quoted}))
    readiness = check_data_readiness(snapshot["evidence"], analysis_date="2026-10-15", horizon="curto")
    assert expected in readiness["reason"]


def test_coleta_preserva_payload_com_uma_unica_consulta_por_fonte():
    config = SimpleNamespace(db_path="nao-abrir.duckdb", fund_ttl=86400)
    payload = fund(**{"Campo adicional": "Preservado"})
    with patch("b3_report.sources.yfinance.extract_yfinance_info", return_value="{}") as yf, \
            patch("b3_report.sources.fundamentus.get_complementary_payload", return_value=payload) as fundamentus, \
            patch("b3_report.sources.cvm.fetch_raw_rows", return_value=[]) as cvm:
        snapshot = collect_snapshot("FIIB11", config, "2026-10-15")
    yf.assert_called_once_with("FIIB11.SA")
    fundamentus.assert_called_once_with("FIIB11", db_path=config.db_path, ttl_seconds=86400)
    cvm.assert_called_once_with("FIIB11", config.db_path)
    assert snapshot["source_data"]["fundamentus"] == payload
    assert snapshot["evidence"]["valuation"]["source"] == "fundamentus"


def test_payload_textual_antigo_continua_valido_e_nao_e_reinterpretado():
    snapshot = build()
    assert snapshot["source_data"]["fundamentus"] == "Texto simulado."
    assert snapshot["normalization_policy"] == "yfinance-primary-v1"
    assert snapshot["evidence"]["valuation"]["value"] == {}
    assert snapshot_id(snapshot)


@pytest.mark.parametrize("quote_type", ["EQUITY", "ETF", None])
def test_tipologia_declarada_preservada_sem_inferencia_por_ticker(quote_type):
    stock = Mock(info={"quoteType": quote_type}, recommendations=None)
    with patch("b3_report.sources.yfinance.yf.Ticker", return_value=stock):
        data = json.loads(extract_yfinance_info("TEST11.SA"))
    assert data["Basic Info"]["Quote Type"] == quote_type


def test_cache_remove_campos_antigos_sem_misturar_coletas(tmp_path):
    path = str(tmp_path / "cache.duckdb")
    save_cache(path, "FIIB11", {"P/VP": "0,73", "Antigo": "123"}, datetime(2026, 10, 14))
    save_cache(path, "FIIB11", {"P/VP": "0,74"}, datetime(2026, 10, 15))
    assert load_cache(path, "FIIB11") == {"P/VP": "0,74"}


def test_cache_legado_misturado_le_apenas_ultima_coleta(tmp_path):
    path = str(tmp_path / "cache.duckdb")
    save_cache(path, "FIIB11", {"Antigo": "123"}, datetime(2026, 10, 14))
    con = duckdb.connect(path)
    con.execute("INSERT INTO fundamentus_cache VALUES (?, ?, ?, ?, ?)",
                ["FIIB11", "P/VP", "0,73", "fundamentus.com.br", datetime(2026, 10, 15)])
    con.close()
    assert load_cache(path, "FIIB11") == {"P/VP": "0,73"}


def test_cache_falha_reverte_substituicao(tmp_path):
    path = str(tmp_path / "cache.duckdb")
    save_cache(path, "FIIB11", {"P/VP": "0,73"}, datetime(2026, 10, 14))
    with pytest.raises(Exception):
        save_cache(path, "FIIB11", {None: "invalido"}, datetime(2026, 10, 15))
    assert load_cache(path, "FIIB11") == {"P/VP": "0,73"}
