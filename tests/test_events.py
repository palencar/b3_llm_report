from copy import deepcopy
from datetime import datetime
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from b3_report.events import (
    active_event, event_lines, event_summary_lines, event_token, load_event_context, validate_event_context,
)


def event(**changes):
    return {"id": "resultado-teste", "ticker": "WEGE3", "type": "resultados",
            "event_date": "2026-10-22", "event_time": None, "timezone": "America/Sao_Paulo",
            "source": "https://ri.exemplo.test/calendario", "available_at": "2026-10-19T10:00:00-03:00",
            "checked_at": "2026-10-21T08:00:00-03:00", "status": "previsto",
            "incorporation": "nao_verificado", "incorporated_at": None, **changes}


def calendar(tmp_path, entries=None):
    path = tmp_path / "events.json"
    path.write_text(json.dumps({"version": "corporate-events-v1", "events": entries if entries is not None else [event()]}))
    return SimpleNamespace(corporate_events_file=str(path))


def load(config, timestamp="2026-10-21T12:00:00+00:00"):
    return load_event_context(config, "WEGE3", as_of=datetime.fromisoformat(timestamp))


def test_opcional_nao_abre_calendario():
    assert load_event_context(SimpleNamespace(), "WEGE3") is None


@pytest.mark.parametrize("changes,expected", [
    ({"status": "cancelado"}, "cancelado"),
    ({"status": "divulgado", "event_date": "2026-10-20"}, "divulgado; atualizacao dos dados pendente"),
])
def test_resumo_preserva_situacao_evento_manual(tmp_path, changes, expected):
    context = load(calendar(tmp_path, [event(**changes)]))
    summary = " ".join(event_summary_lines(context))
    assert expected in summary
    assert "Fonte: https://ri.exemplo.test/calendario" in summary


@pytest.mark.parametrize("timestamp,phase", [
    ("2026-10-21T12:00:00+00:00", "evento_proximo"),
    ("2026-10-22T12:00:00+00:00", "evento_hoje_horario_desconhecido"),
    ("2026-10-23T12:00:00+00:00", "data_prevista_atingida_confirmacao_pendente"),
])
def test_fases_nao_presumem_divulgacao_ou_atualizacao(tmp_path, timestamp, phase):
    context = load(calendar(tmp_path), timestamp)
    assert context["events"][0]["phase"] == phase
    assert context["events"][0]["incorporation"] == "nao_verificado"


def test_horario_e_fuso_distinguem_antes_e_depois(tmp_path):
    config = calendar(tmp_path, [event(event_time="18:00")])
    assert load(config, "2026-10-22T20:59:00Z")["events"][0]["phase"] == "evento_proximo"
    assert load(config, "2026-10-22T21:00:00Z")["events"][0]["phase"] == "data_prevista_atingida_confirmacao_pendente"


def test_conhecimento_futuro_e_outro_ticker_nao_entram_no_snapshot(tmp_path):
    config = calendar(tmp_path, [event(checked_at="2026-10-22T08:00:00-03:00"), event(id="outro", ticker="ABEV3")])
    assert load(config)["events"] == []
    assert not active_event(load(config))


def test_divulgado_nao_significa_incorporado(tmp_path):
    config = calendar(tmp_path, [event(event_date="2026-10-20", status="divulgado")])
    assert load(config)["events"][0]["phase"] == "divulgado_atualizacao_pendente"
    config = calendar(tmp_path, [event(event_date="2026-10-20", status="divulgado", incorporation="atualizados",
                                      incorporated_at="2026-10-20T20:00:00-03:00")])
    assert load(config)["events"][0]["phase"] == "incorporado"
    assert not active_event(load(config))


@pytest.mark.parametrize("changes", [
    {"available_at": "2026-10-21T09:00:00"}, {"source": ""}, {"event_time": "25:00"},
    {"incorporation": "atualizados"}, {"status": "divulgado"},
    {"available_at": "2026-10-22T09:00:00-03:00"},
])
def test_calendario_invalido_falha_explicitamente(tmp_path, changes):
    with pytest.raises(ValueError):
        load(calendar(tmp_path, [event(**changes)]))


def test_token_nao_muda_a_cada_poll_mas_muda_na_fronteira(tmp_path):
    config = calendar(tmp_path)
    assert event_token(load(config)) == event_token(load(config, "2026-10-21T12:01:00Z"))
    assert event_token(load(config)) != event_token(load(config, "2026-10-22T12:01:00Z"))


def test_evento_cancelado_ou_distante_nao_ativa_bypass(tmp_path):
    assert not active_event(load(calendar(tmp_path, [event(status="cancelado")])))
    assert not active_event(load(calendar(tmp_path, [event(event_date="2026-12-01")])))


@pytest.mark.parametrize("timestamp,old", [
    ("2026-10-30T02:59:59Z", False),
    ("2026-10-30T03:00:00Z", True),
])
def test_limite_de_pendencia_sete_dias_corridos_no_fuso_local(tmp_path, timestamp, old):
    result = load(calendar(tmp_path), timestamp)
    assert result["pending_days"] == 7
    assert (result["events"][0]["phase"] == "evento_antigo_verificacao_pendente") is old
    assert active_event(result) is not old
    assert result["events"][0]["status"] == "previsto"
    assert result["events"][0]["incorporation"] == "nao_verificado"
    validate_event_context(result, "WEGE3", datetime.fromisoformat(timestamp).date().isoformat())


def test_pendencia_antiga_preserva_divulgacao_confirmada_sem_alerta_iminente(tmp_path):
    result = load(calendar(tmp_path, [event(event_date="2026-10-20", status="divulgado")]),
                  "2026-10-30T12:00:00Z")
    assert result["events"][0]["phase"] == "evento_antigo_verificacao_pendente"
    assert result["events"][0]["status"] == "divulgado"
    assert result["events"][0]["incorporation"] == "nao_verificado"
    assert not active_event(result)
    assert not any(line.startswith("Atencao:") for line in event_lines(result))


@pytest.mark.parametrize("changes,phase", [
    ({"status": "cancelado"}, "cancelado"),
    ({"status": "divulgado", "incorporation": "atualizados",
      "incorporated_at": "2026-10-22T20:00:00-03:00",
      "checked_at": "2026-10-23T08:00:00-03:00"}, "incorporado"),
])
def test_expiracao_nao_substitui_cancelamento_ou_incorporacao(tmp_path, changes, phase):
    result = load(calendar(tmp_path, [event(**changes)]), "2026-10-30T12:00:00Z")
    assert result["events"][0]["phase"] == phase


def test_replay_de_contexto_v1_preserva_semantica_e_conteudo(tmp_path):
    result = load(calendar(tmp_path), "2026-10-30T12:00:00Z")
    result["policy_version"] = "eventos-v1-experimental-7d"
    result.pop("pending_days")
    result["events"][0]["phase"] = "data_prevista_atingida_confirmacao_pendente"
    before = deepcopy(result)
    validate_event_context(result, "WEGE3", "2026-10-30")
    assert active_event(result)
    assert result == before
    result["policy_version"] = "eventos-v2-experimental-7d"
    result["pending_days"] = 7
    with pytest.raises(ValueError, match="fase"):
        validate_event_context(result, "WEGE3", "2026-10-30")


def test_snapshot_rejeita_contexto_de_outro_instante_ou_fase(tmp_path):
    context = load(calendar(tmp_path))
    with pytest.raises(ValueError):
        validate_event_context(context, "WEGE3", "2026-10-20")
    context["events"][0]["phase"] = "incorporado"
    with pytest.raises(ValueError):
        validate_event_context(context, "WEGE3", "2026-10-21")


def test_eventos_duplicados_nao_sao_silenciosamente_conciliados(tmp_path):
    with pytest.raises(ValueError, match="duplicado"):
        load(calendar(tmp_path, [event(), event()]))


def test_relatorio_legado_recebe_contexto_e_persiste_aviso(tmp_path, monkeypatch):
    from unittest.mock import Mock
    from b3_report import cli
    context = load(calendar(tmp_path))
    config = SimpleNamespace(raw_dir=str(tmp_path / "raw"), ollama_url_base="http://simulado", openai_url_base="",
        llm_model="texto", llm_api_key="", db_path="simulado", fund_ttl=1, report_history_n=1)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "load_dotenv", Mock())
    monkeypatch.setattr(cli, "load_config", Mock(return_value=config))
    monkeypatch.setattr(cli, "load_event_context", Mock(return_value=context))
    for name in ("get_yfinance_data", "get_complementary_data", "get_cvm_data", "get_recent_reports_history"):
        monkeypatch.setattr(cli, name, Mock(return_value="dados simulados"))
    monkeypatch.setattr(cli, "prepare_llm_investment_analysis_request", Mock(return_value="Prompt simulado"))
    monkeypatch.setattr(cli, "_validate_report_content", Mock())
    request = Mock(return_value="WEGE3 - relatorio simulado")
    monkeypatch.setattr(cli, "get_investment_analysis", request)
    report = cli.run_report("WEGE3")
    assert "eventos-v2-experimental-7d" in request.call_args.args[0]
    assert "evento proximo" in report
    assert "WEGE3" in (tmp_path / "reports" / "WEGE3.md").read_text()
    assert len(list((tmp_path / "raw" / "events" / "WEGE3").glob("*.json"))) == 1
