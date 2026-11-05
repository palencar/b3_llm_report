from copy import deepcopy
from datetime import datetime
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from b3_report.events import (
    AUTO_EVENT_POLICY_VERSION, active_event, event_lines, event_summary_lines, event_token, load_event_context, validate_event_context,
)
from b3_report.sources.yfinance import _event_metadata


def data(raw=None, fetched="2026-10-21T19:00:00+00:00"):
    return {"Source Metadata": {"Fetched At": fetched}, "Event Metadata": _event_metadata(raw if raw is not None else {
        "earningsTimestamp": 1792612800, "earningsTimestampStart": 1792612800,
        "earningsTimestampEnd": 1792612800, "isEarningsDateEstimate": False,
        "exchangeTimezoneName": "America/Sao_Paulo"})}


def context(tmp_path, timestamp="2026-10-21T19:01:00+00:00", payload=None):
    return load_event_context(SimpleNamespace(raw_dir=str(tmp_path)), "WEGE3",
        as_of=datetime.fromisoformat(timestamp), yfinance_data=payload or data())


def test_dados_observados_wege3_geram_aviso_sem_calendario_manual(tmp_path):
    result = context(tmp_path)
    assert result["policy_version"] == AUTO_EVENT_POLICY_VERSION
    event = result["events"][0]
    assert event["event_date"] == "2026-10-21"
    assert event["event_time"] == "17:00"
    assert event["timezone"] == "America/Sao_Paulo"
    assert event["phase"] == "evento_proximo"
    assert event["certainty"] == "nao_marcada_como_estimativa"
    assert event["status"] == "previsto"
    assert event["incorporation"] == "nao_verificado"
    assert event["publication_at"] is event["incorporated_at"] is None
    assert active_event(result)
    validate_event_context(result, "WEGE3", "2026-10-21")
    assert "nao confirmado pelo RI" in " ".join(event_lines(result))


def test_cache_recalcula_fase_sem_consultar_yahoo(tmp_path):
    config = SimpleNamespace(raw_dir=str(tmp_path))
    before = context(tmp_path)
    with patch("b3_report.sources.yfinance.yf.Ticker", side_effect=AssertionError("Nao consultar Yahoo")):
        same = load_event_context(config, "WEGE3", as_of=datetime.fromisoformat("2026-10-21T19:02:00Z"))
        after = load_event_context(config, "WEGE3", as_of=datetime.fromisoformat("2026-10-21T20:00:00Z"))
    assert event_token(before) == event_token(same)
    assert event_token(before) != event_token(after)
    assert after["events"][0]["phase"] == "data_prevista_atingida_confirmacao_pendente"
    assert after["events"][0]["incorporation"] == "nao_verificado"


def test_resumo_preserva_contexto_sem_metadados_operacionais(tmp_path):
    result = context(tmp_path)
    before = deepcopy(result)
    detailed = " ".join(event_lines(result))
    summary = " ".join(event_summary_lines(result))
    assert "21/10/2026 17:00 America/Sao_Paulo" in summary
    assert "evento proximo" in summary and "Fonte: Yahoo Finance" in summary
    assert "nao confirmados pelo RI" in summary and "Calendario parcial" in summary
    assert "descontinuidade" in summary
    assert "consultado=" not in summary and "timestamp pontual=" not in summary
    assert len(summary) < len(detailed)
    assert result == before


def test_resumo_intervalo_estimado_e_divergencia_nao_sao_ocultados(tmp_path):
    payload = data({"earningsTimestampStart": 1792612800, "earningsTimestampEnd": 1792699200,
                    "isEarningsDateEstimate": True})
    result = context(tmp_path, "2026-10-21T21:00:00Z", payload)
    summary = " ".join(event_summary_lines(result))
    assert "intervalo 2026-10-21T20:00:00+00:00 a 2026-10-22T20:00:00+00:00" in summary
    assert "estimativa" in summary and "intervalo previsto em curso" in summary
    result = context(tmp_path, payload=data({"earningsTimestamp": 1792526400,
        "earningsTimestampStart": 1792612800, "earningsTimestampEnd": 1792699200}))
    summary = " ".join(event_summary_lines(result))
    assert "datas divergentes" in summary and "data pontual divergente:" in summary


def test_resumo_sem_eventos_nao_afirma_ausencia_de_risco(tmp_path):
    assert event_summary_lines(None) == []
    summary = " ".join(event_summary_lines(context(tmp_path, payload=data({}))))
    assert "Nenhuma data" in summary and "ausencia de registro nao significa ausencia de eventos" in summary
    assert "Atencao:" not in summary


def test_resumo_evento_antigo_nao_emite_alerta_ativo(tmp_path):
    result = context(tmp_path, "2026-11-01T19:01:00+00:00")
    summary = " ".join(event_summary_lines(result))
    assert "data antiga" in summary and "verificacao pendente" in summary
    assert "Atencao:" not in summary


def test_intervalo_e_estimativa_nao_viram_horario_exato(tmp_path):
    payload = data({"earningsTimestampStart": 1792612800, "earningsTimestampEnd": 1792699200,
                    "isEarningsDateEstimate": True})
    result = context(tmp_path, "2026-10-21T21:00:00Z", payload)
    event = result["events"][0]
    assert event["event_time"] is None
    assert event["certainty"] == "estimativa"
    assert event["phase"] == "intervalo_previsto_em_curso"
    assert event["timezone"] == "UTC"
    assert event["provider_start_at"] != event["provider_end_at"]


def test_sem_datas_ou_somente_call_nao_fabrica_evento_de_resultado(tmp_path):
    for raw in ({}, {"earningsCallTimestamp": 1792612800}, {"earningsTimestampStart": 1792612800}):
        result = context(tmp_path, payload=data(raw))
        assert result["events"] == []
        assert not active_event(result)


def test_intervalo_e_timestamp_pontual_divergentes_sao_sinalizados(tmp_path):
    result = context(tmp_path, payload=data({"earningsTimestamp": 1792526400,
        "earningsTimestampStart": 1792612800, "earningsTimestampEnd": 1792699200}))
    assert result["events"][0]["phase"] == "datas_divergentes_verificacao_pendente"


def test_evento_antigo_abcb4_preservado_sem_alerta_ativo(tmp_path):
    payload = data({"earningsTimestampStart": 1754569800, "earningsTimestampEnd": 1754569800,
                    "isEarningsDateEstimate": False, "exchangeTimezoneName": "America/Sao_Paulo"},
                   fetched="2026-10-23T14:34:38.557775+00:00")
    result = context(tmp_path, "2026-10-23T14:34:39.227915+00:00", payload)
    item = result["events"][0]
    assert item["event_date"] == "2025-08-07"
    assert item["phase"] == "evento_antigo_verificacao_pendente"
    assert item["status"] == "previsto" and item["incorporation"] == "nao_verificado"
    assert item["provider_start_at"] == "2025-08-07T12:30:00+00:00"
    assert not active_event(result)
    assert not any(line.startswith("Atencao:") for line in event_lines(result))
    assert "Data antiga" in " ".join(event_lines(result))
    validate_event_context(result, "WEGE3", "2026-10-23")


@pytest.mark.parametrize("timestamp,old", [
    ("2026-10-30T02:59:59Z", False), ("2026-10-30T03:00:00Z", True),
])
def test_expiracao_de_intervalo_conta_do_fim_nao_do_inicio(tmp_path, timestamp, old):
    payload = data({"earningsTimestampStart": 1792612800, "earningsTimestampEnd": 1792699200,
                    "exchangeTimezoneName": "America/Sao_Paulo"})
    result = context(tmp_path, timestamp, payload)
    assert (result["events"][0]["phase"] == "evento_antigo_verificacao_pendente") is old
    assert active_event(result) is not old


def test_data_divergente_futura_nao_e_ocultada_como_antiga(tmp_path):
    payload = data({"earningsTimestampStart": 1754569800, "earningsTimestampEnd": 1754569800,
                    "earningsTimestamp": 1792612800})
    result = context(tmp_path, "2026-10-21T19:01:00Z", payload)
    assert result["events"][0]["phase"] == "datas_divergentes_verificacao_pendente"
    assert active_event(result)


def test_replay_auto_v1_aceita_pendencia_antiga_sem_reclassificar(tmp_path):
    result = context(tmp_path, "2026-11-10T19:01:00Z")
    result["policy_version"] = "eventos-yahoo-v1-experimental-7d"
    result.pop("pending_days")
    result["events"][0]["phase"] = "data_prevista_atingida_confirmacao_pendente"
    before = deepcopy(result)
    validate_event_context(result, "WEGE3", "2026-11-10")
    assert result == before


def test_conhecimento_futuro_nao_e_injetado(tmp_path):
    assert context(tmp_path, "2026-10-21T18:00:00Z")["events"] == []


def test_replay_de_snapshot_nao_le_cache_atual(tmp_path):
    from b3_report.unified import classify_unified_snapshot
    from b3_report.snapshot import build_snapshot
    # Snapshot historico sem calendario continua sem calendario no replay.
    snapshot = build_snapshot(ticker="WEGE3", analysis_date="2026-10-13", yfinance_data={},
                                       fundamentus_text="", cvm_rows=[])
    before = deepcopy(snapshot)
    context(tmp_path)
    with patch("b3_report.events.load_event_context", side_effect=AssertionError("Nao ler calendario atual")):
        result = classify_unified_snapshot(snapshot, model="modelo",
                                   requester=Mock(side_effect=AssertionError("Gates insuficientes")))
    assert "event_context" not in result
    assert snapshot == before


def test_contexto_auto_adulterado_e_rejeitado(tmp_path):
    result = context(tmp_path)
    result["events"][0]["status"] = "divulgado"
    with pytest.raises(ValueError):
        validate_event_context(result, "WEGE3", "2026-10-21")


def test_observacao_persistida_preserva_dados_brutos(tmp_path):
    original = data()
    context(tmp_path, payload=original)
    saved = json.loads((tmp_path / "event-observations" / "WEGE3.json").read_text())
    assert saved["metadata"] == original["Event Metadata"]
    assert saved["observed_at"] == original["Source Metadata"]["Fetched At"]


def test_recoleta_igual_nao_invalida_fila_apenas_pelo_horario(tmp_path):
    first = context(tmp_path)
    second = context(tmp_path, "2026-10-21T19:31:00Z", data(fetched="2026-10-21T19:30:00Z"))
    assert first["events"][0]["checked_at"] != second["events"][0]["checked_at"]
    assert event_token(first) == event_token(second)


def test_coleta_do_snapshot_normaliza_e_preserva_metadados_sem_calendario(tmp_path):
    from b3_report.snapshot import collect_snapshot
    config = SimpleNamespace(raw_dir=str(tmp_path), db_path="simulado", fund_ttl=1)
    payload = data()
    fixed = datetime.fromisoformat("2026-10-21T19:01:00Z")
    with patch("b3_report.sources.yfinance.extract_yfinance_info", return_value=json.dumps(payload)), \
         patch("b3_report.sources.fundamentus.get_complementary_payload", return_value={"text": "", "indicators": {}, "fetched_at": None}), \
         patch("b3_report.sources.cvm.fetch_raw_rows", return_value=[]), \
         patch("b3_report.events.datetime", wraps=datetime) as clock:
        clock.now.return_value = fixed
        snapshot = collect_snapshot("WEGE3", config, "2026-10-21")
    assert snapshot["event_context"]["events"][0]["event_time"] == "17:00"
    assert snapshot["source_data"]["yfinance"] == payload
    assert snapshot["risk_evidence"] == {}


def test_watcher_percebe_mudanca_de_fase_do_cache_sem_chamada_de_rede(tmp_path):
    import watch_queue
    config = SimpleNamespace(raw_dir=str(tmp_path), report_min_age_hours=24, llm_model="modelo",
                             ollama_url_base="http://simulado", openai_url_base="")
    before = context(tmp_path)
    state_path = watch_queue.queue_state_path(config, "WEGE3")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"event_state": event_token(before)}))
    after = load_event_context(config, "WEGE3", as_of=datetime.fromisoformat("2026-10-21T20:00:00Z"))
    with patch("watch_queue.load_event_context", return_value=after):
        assert watch_queue._calendar_changed(config, "WEGE3", after)


def test_formatador_legado_consumidor_recebe_mesmo_json_uma_vez():
    from b3_report.sources.yfinance import get_yfinance_data
    received = []
    # A coleta e simulada; nao acessa Ticker ou recomendacoes reais.
    from b3_report.sources.yfinance import extract_yfinance_info
    stock = Mock(info={"symbol": "WEGE3.SA", "earningsTimestamp": 1792612800}, recommendations=None)
    with patch("b3_report.sources.yfinance.yf.Ticker", return_value=stock):
        source = extract_yfinance_info("WEGE3.SA")
    with patch("b3_report.sources.yfinance.extract_yfinance_info", return_value=source) as extract:
        text = get_yfinance_data("WEGE3.SA", on_data=received.append)
    extract.assert_called_once_with("WEGE3.SA")
    assert received == [json.loads(source)]
    assert "earningsTimestamp" in text
