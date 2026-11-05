"""Testes do fluxo unico da fila, sem fontes ou modelos reais."""

import json
import logging
import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

import watch_queue as watcher


@pytest.fixture
def config(tmp_path, monkeypatch):
    queue = tmp_path / "queue"
    queue.mkdir()
    monkeypatch.setattr(watcher, "REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(watcher, "_NEXT_ATTEMPT_AT", 0)
    monkeypatch.setattr(watcher, "_LAST_ATTEMPTED_ENTRY", None)
    monkeypatch.setattr(watcher, "_IGNORED_STALE_TRIGGERS", {})
    monkeypatch.setattr(watcher, "_SKIPPED_TRIGGERS", {})
    monkeypatch.setattr(watcher, "_CONTROL_ERRORS", {})
    monkeypatch.setattr(watcher, "load_event_context", Mock(return_value=None))
    monkeypatch.setattr(watcher, "should_run_report", Mock(return_value=(True, "simulado")))
    monkeypatch.setattr(watcher, "run_report", Mock(return_value={"results": {}, "failed_modes": []}))
    monkeypatch.setattr(watcher.time, "time", lambda: 1000000)
    monkeypatch.setattr(watcher.time, "monotonic", lambda: 100)
    return SimpleNamespace(queue_dir=str(queue), raw_dir=str(tmp_path / "raw"),
                           queue_max_trigger_age_hours=24, queue_request_interval_seconds=60,
                           queue_error_cooldown_seconds=900, report_min_age_hours=24)


def trigger(config, ticker, timestamp=1000000):
    from pathlib import Path
    path = Path(config.queue_dir) / ticker
    path.touch()
    os.utime(path, (timestamp, timestamp))
    return path


def test_sem_flags_usa_estado_unificado_e_preserva_alerta(config):
    path = trigger(config, "wege3")
    watcher._process_queue(config)
    watcher.should_run_report.assert_called_once_with(config, "WEGE3", path.stat().st_mtime)
    watcher.run_report.assert_called_once_with("WEGE3", config=config,
        trigger_mtime=path.stat().st_mtime, reports_dir=watcher.REPORTS_DIR)
    assert path.exists()


def test_skip_loga_uma_vez_por_alerta(config, caplog):
    path = trigger(config, "WEGE3")
    watcher.should_run_report.return_value = (False, "relatorio unificado ja concluido")
    with caplog.at_level(logging.INFO):
        watcher._process_queue(config)
        watcher._process_queue(config)
        os.utime(path, (1000001, 1000001))
        watcher._process_queue(config)
    assert sum(record.message.startswith("skipped WEGE3") for record in caplog.records) == 2
    watcher.run_report.assert_not_called()


def test_alerta_antigo_ignorado_sem_consultar_modelo(config):
    path = trigger(config, "WEGE3", 1000000 - 7 * 86400)
    watcher._process_queue(config)
    watcher.should_run_report.assert_not_called()
    watcher.run_report.assert_not_called()
    assert path.exists()


def test_evento_ativo_permite_avaliar_alerta_antigo(config, monkeypatch):
    trigger(config, "WEGE3", 1000000 - 7 * 86400)
    monkeypatch.setattr(watcher, "active_event", lambda context: True)
    watcher._process_queue(config)
    watcher.run_report.assert_called_once()


def test_item_invalido_e_diretorio_ignorados(config):
    from pathlib import Path
    trigger(config, "INVALIDO!")
    (Path(config.queue_dir) / "ABEV3").mkdir()
    watcher._process_queue(config)
    watcher.run_report.assert_not_called()


def test_fila_inexistente_nao_chama_modelo(config):
    from pathlib import Path
    Path(config.queue_dir).rmdir()
    watcher._process_queue(config)
    watcher.run_report.assert_not_called()


def test_itens_espacados_e_processados_em_ordem(config, monkeypatch):
    first = trigger(config, "ABEV3")
    second = trigger(config, "WEGE3")
    watcher._process_queue(config)
    assert watcher.run_report.call_count == 1
    monkeypatch.setattr(watcher.time, "monotonic", lambda: 159)
    watcher._process_queue(config)
    assert watcher.run_report.call_count == 1
    monkeypatch.setattr(watcher.time, "monotonic", lambda: 160)
    watcher._process_queue(config)
    assert [call.args[0] for call in watcher.run_report.call_args_list] == ["ABEV3", "WEGE3"]
    assert first.exists() and second.exists()


@pytest.mark.parametrize("failure", ["excecao", "resultado"])
def test_falha_pausa_e_retoma_no_proximo_item(config, monkeypatch, caplog, failure):
    first = trigger(config, "ABEV3")
    second = trigger(config, "WEGE3")
    failed = RuntimeError("Falha simulada") if failure == "excecao" else {
        "results": {}, "failed_modes": ["unified"]}
    watcher.run_report.side_effect = [failed, {"results": {}, "failed_modes": []}]
    watcher._process_queue(config)
    assert watcher._NEXT_ATTEMPT_AT == 1000
    monkeypatch.setattr(watcher.time, "monotonic", lambda: 999)
    watcher._process_queue(config)
    assert watcher.run_report.call_count == 1
    monkeypatch.setattr(watcher.time, "monotonic", lambda: 1000)
    watcher._process_queue(config)
    assert watcher.run_report.call_count == 2
    assert watcher.run_report.call_args.args[0] == "WEGE3"
    assert "fila pausada por 900s" in caplog.text
    assert first.exists() and second.exists()


def test_estado_corrompido_nao_impede_demais_itens(config, monkeypatch, caplog):
    trigger(config, "ABEV3")
    trigger(config, "WEGE3")
    monkeypatch.setattr(watcher, "load_event_context", lambda *args: {"token": "atual"})
    monkeypatch.setattr(watcher, "active_event", lambda context: False)
    path = watcher.queue_state_path(config, "ABEV3")
    path.parent.mkdir(parents=True)
    path.write_text("{", encoding="utf-8")
    watcher._process_queue(config)
    assert "item preservado" in caplog.text
    assert watcher.run_report.call_args.args[0] == "WEGE3"


def test_detecta_mudanca_de_evento_no_estado_unico(config, monkeypatch):
    reader = Mock(return_value={"event_state": "anterior"})
    monkeypatch.setattr(watcher, "load_report_state", reader)
    monkeypatch.setattr(watcher, "event_token", lambda context: context["token"])
    assert watcher._calendar_changed(config, "WEGE3", {"token": "atual"})
    assert not watcher._calendar_changed(config, "WEGE3", {"token": "anterior"})
    assert reader.call_count == 2
    reader.assert_called_with(config, "WEGE3")


def test_controle_invalido_loga_uma_vez_mas_verifica_em_toda_varredura(config, caplog):
    path = trigger(config, "WEGE3")
    watcher.should_run_report.side_effect = ValueError("Pendencia incompativel")
    with caplog.at_level(logging.ERROR):
        watcher._process_queue(config)
        watcher._process_queue(config)
        watcher._process_queue(config)
    assert watcher.should_run_report.call_count == 3
    assert caplog.text.count("Pendencia incompativel") == 1
    watcher.run_report.assert_not_called()
    assert path.exists()


@pytest.mark.parametrize("changed", ["alerta", "estado", "pedido", "motivo"])
def test_erro_de_controle_volta_ao_log_quando_muda(config, caplog, changed):
    path = trigger(config, "WEGE3")
    watcher.should_run_report.side_effect = ValueError("Pendencia incompativel")
    with caplog.at_level(logging.ERROR):
        watcher._process_queue(config)
        watcher._process_queue(config)
        if changed == "alerta":
            os.utime(path, (1000001, 1000001))
        elif changed == "estado":
            state = watcher.queue_state_path(config, "WEGE3")
            state.parent.mkdir(parents=True)
            state.write_text("{}")
        elif changed == "pedido":
            manual_request(config, "WEGE3")
        else:
            watcher.should_run_report.side_effect = ValueError("Outra pendencia")
        watcher._process_queue(config)
    errors = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert len(errors) == 2
    watcher.run_report.assert_not_called()


def test_erro_de_controle_volta_ao_log_apos_recuperacao(config, caplog):
    trigger(config, "WEGE3")
    watcher.should_run_report.side_effect = ValueError("Pendencia incompativel")
    with caplog.at_level(logging.ERROR):
        watcher._process_queue(config)
        watcher.should_run_report.side_effect = None
        watcher.should_run_report.return_value = (False, "relatorio unificado ja concluido")
        watcher._process_queue(config)
        watcher.should_run_report.side_effect = ValueError("Pendencia incompativel")
        watcher._process_queue(config)
    assert caplog.text.count("Pendencia incompativel") == 2


def test_pedido_invalido_nao_repete_log_e_pode_ser_corrigido(config, caplog):
    from b3_report.queue_control import request_path
    trigger(config, "WEGE3")
    path = request_path(config.queue_dir, "WEGE3")
    path.parent.mkdir()
    path.write_text("{}")
    with caplog.at_level(logging.ERROR):
        watcher._process_queue(config)
        watcher._process_queue(config)
    assert caplog.text.count("Solicitacao manual invalida") == 1
    path.unlink()
    watcher._process_queue(config)
    watcher.run_report.assert_called_once()


def manual_request(config, ticker):
    from b3_report.queue_control import enqueue_request, read_request

    enqueue_request(config.queue_dir, ticker)
    return read_request(config.queue_dir, ticker)


def test_solicitacao_obrigatoria_sem_alerta_processa_e_remove_pedido(config):
    from b3_report.queue_control import request_path

    request = manual_request(config, "WEGE3")
    watcher._process_queue(config)
    watcher.should_run_report.assert_called_once_with(
        config, "WEGE3", request["requested_at"], request_id=request["id"])
    watcher.run_report.assert_called_once_with(
        "WEGE3", config=config, trigger_mtime=request["requested_at"],
        reports_dir=watcher.REPORTS_DIR, request_id=request["id"])
    assert not request_path(config.queue_dir, "WEGE3").exists()


def test_solicitacao_obrigatoria_nao_expira_e_preserva_alerta(config):
    path = trigger(config, "wege3", 1000000 - 7 * 86400)
    manual_request(config, "WEGE3")
    watcher._process_queue(config)
    assert watcher.run_report.call_count == 1
    assert path.stat().st_mtime == 1000000 - 7 * 86400


@pytest.mark.parametrize("failure", ["excecao", "resultado"])
def test_pedido_manual_preservado_apos_falha(config, failure):
    from b3_report.queue_control import read_request

    request = manual_request(config, "WEGE3")
    if failure == "excecao":
        watcher.run_report.side_effect = RuntimeError("Falha simulada")
    else:
        watcher.run_report.return_value = {"results": {}, "failed_modes": ["unified"]}
    watcher._process_queue(config)
    assert read_request(config.queue_dir, "WEGE3") == request
    assert watcher._NEXT_ATTEMPT_AT == 1000


def test_pedido_ja_concluido_remove_marcador_sem_nova_chamada(config):
    from b3_report.queue_control import request_path

    manual_request(config, "WEGE3")
    watcher.should_run_report.return_value = (False, "solicitacao manual ja concluida")
    watcher._process_queue(config)
    watcher.run_report.assert_not_called()
    assert not request_path(config.queue_dir, "WEGE3").exists()


def test_watcher_bloqueia_ativo_durante_execucao(config):
    from b3_report.queue_control import TickerBusy, processing_lock, request_lock

    trigger(config, "WEGE3")
    def execute(*args, **kwargs):
        # A coleta/inferencia nao mantem o controle curto do registro.
        with request_lock(config.queue_dir, "WEGE3"):
            pass
        with pytest.raises(TickerBusy):
            with processing_lock(config.queue_dir, "WEGE3"):
                pytest.fail("Ativo nao protegido durante processamento")
        return {"results": {}, "failed_modes": []}
    watcher.run_report.side_effect = execute
    watcher._process_queue(config)
    assert watcher.run_report.call_count == 1


def test_pedido_durante_verificacao_ignorada_nao_e_perdido(config, monkeypatch, capsys):
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path
    import runpy
    from threading import Event
    from b3_report.queue_control import read_request, request_lock

    cli = runpy.run_path(str(Path(__file__).resolve().parents[1] / "relatorio"))["main"]
    trigger(config, "WEGE3")
    waiting = Event()
    submitted = []
    def observe_lock(*args, **kwargs):
        waiting.set()
        return request_lock(*args, **kwargs)
    with ThreadPoolExecutor(max_workers=1) as executor:
        def eligibility(*args, **kwargs):
            submitted.append(executor.submit(cli, ["gerar", "WEGE3", "--diretorio-fila", config.queue_dir]))
            assert waiting.wait(timeout=5)
            return False, "relatorio unificado muito recente"
        monkeypatch.setattr(watcher.should_run_report, "side_effect", eligibility)
        with patch("b3_report.queue_control.request_lock", side_effect=observe_lock):
            watcher._process_queue(config)
            assert submitted[0].result(timeout=5) == 0
    watcher.run_report.assert_not_called()
    request = read_request(config.queue_dir, "WEGE3")
    assert request is not None
    assert "Solicitacao registrada" in capsys.readouterr().out
    watcher.should_run_report.side_effect = None
    watcher.should_run_report.return_value = (True, "atualizacao obrigatoria solicitada")
    watcher._process_queue(config)
    assert watcher.run_report.call_args.kwargs["request_id"] == request["id"]
    assert read_request(config.queue_dir, "WEGE3") is None


def test_cli_nao_agenda_segunda_geracao_quando_ativo_em_processamento(config, capsys):
    from pathlib import Path
    import runpy
    from b3_report.queue_control import read_request

    cli = runpy.run_path(str(Path(__file__).resolve().parents[1] / "relatorio"))["main"]
    trigger(config, "WEGE3")
    def execute(*args, **kwargs):
        assert cli(["gerar", "WEGE3", "--diretorio-fila", config.queue_dir]) == 0
        assert read_request(config.queue_dir, "WEGE3") is None
        return {"results": {}, "failed_modes": []}
    watcher.run_report.side_effect = execute
    watcher._process_queue(config)
    assert watcher.run_report.call_count == 1
    assert "WEGE3 ja esta em processamento" in capsys.readouterr().out


def test_ativo_ocupado_nao_impede_proximo(config):
    from b3_report.queue_control import processing_lock

    trigger(config, "ABEV3")
    trigger(config, "WEGE3")
    with processing_lock(config.queue_dir, "ABEV3"):
        watcher._process_queue(config)
    assert watcher.run_report.call_args.args[0] == "WEGE3"


def test_pedido_corrompido_nao_impede_proximo(config, caplog):
    from b3_report.queue_control import request_path

    path = request_path(config.queue_dir, "ABEV3")
    path.parent.mkdir()
    path.write_text("{")
    trigger(config, "WEGE3")
    watcher._process_queue(config)
    assert watcher.run_report.call_args.args[0] == "WEGE3"
    assert "Controle de fila invalido ticker=ABEV3" in caplog.text
    assert path.read_text() == "{"


def test_solicitacao_nao_muda_ordem_circular_nem_antecipa_cooldown(config):
    manual_request(config, "WEGE3")
    trigger(config, "ABEV3")
    watcher._process_queue(config)
    assert watcher.run_report.call_args.args[0] == "ABEV3"
    watcher._process_queue(config)
    assert watcher.run_report.call_count == 1
