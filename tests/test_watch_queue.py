"""Testes do fluxo unico da fila, sem fontes ou modelos reais."""

import json
import logging
import os
from types import SimpleNamespace
from unittest.mock import Mock

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
    monkeypatch.setattr(watcher, "load_event_context", Mock(return_value=None))
    monkeypatch.setattr(watcher, "should_run_aligned", Mock(return_value=(True, "simulado")))
    monkeypatch.setattr(watcher, "run_aligned", Mock(return_value={"results": {}, "failed_modes": []}))
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
    watcher.should_run_aligned.assert_called_once_with(config, "WEGE3", path.stat().st_mtime)
    watcher.run_aligned.assert_called_once_with("WEGE3", config=config,
        trigger_mtime=path.stat().st_mtime, reports_dir=watcher.REPORTS_DIR)
    assert path.exists()


def test_skip_loga_uma_vez_por_alerta(config, caplog):
    path = trigger(config, "WEGE3")
    watcher.should_run_aligned.return_value = (False, "relatorio unificado ja concluido")
    with caplog.at_level(logging.INFO):
        watcher._process_queue(config)
        watcher._process_queue(config)
        os.utime(path, (1000001, 1000001))
        watcher._process_queue(config)
    assert sum(record.message.startswith("skipped WEGE3") for record in caplog.records) == 2
    watcher.run_aligned.assert_not_called()


def test_alerta_antigo_ignorado_sem_consultar_modelo(config):
    path = trigger(config, "WEGE3", 1000000 - 7 * 86400)
    watcher._process_queue(config)
    watcher.should_run_aligned.assert_not_called()
    watcher.run_aligned.assert_not_called()
    assert path.exists()


def test_evento_ativo_permite_avaliar_alerta_antigo(config, monkeypatch):
    trigger(config, "WEGE3", 1000000 - 7 * 86400)
    monkeypatch.setattr(watcher, "active_event", lambda context: True)
    watcher._process_queue(config)
    watcher.run_aligned.assert_called_once()


def test_item_invalido_e_diretorio_ignorados(config):
    from pathlib import Path
    trigger(config, "INVALIDO!")
    (Path(config.queue_dir) / "ABEV3").mkdir()
    watcher._process_queue(config)
    watcher.run_aligned.assert_not_called()


def test_fila_inexistente_nao_chama_modelo(config):
    from pathlib import Path
    Path(config.queue_dir).rmdir()
    watcher._process_queue(config)
    watcher.run_aligned.assert_not_called()


def test_itens_espacados_e_processados_em_ordem(config, monkeypatch):
    first = trigger(config, "ABEV3")
    second = trigger(config, "WEGE3")
    watcher._process_queue(config)
    assert watcher.run_aligned.call_count == 1
    monkeypatch.setattr(watcher.time, "monotonic", lambda: 159)
    watcher._process_queue(config)
    assert watcher.run_aligned.call_count == 1
    monkeypatch.setattr(watcher.time, "monotonic", lambda: 160)
    watcher._process_queue(config)
    assert [call.args[0] for call in watcher.run_aligned.call_args_list] == ["ABEV3", "WEGE3"]
    assert first.exists() and second.exists()


@pytest.mark.parametrize("failure", ["excecao", "resultado"])
def test_falha_pausa_e_retoma_no_proximo_item(config, monkeypatch, caplog, failure):
    first = trigger(config, "ABEV3")
    second = trigger(config, "WEGE3")
    failed = RuntimeError("Falha simulada") if failure == "excecao" else {
        "results": {}, "failed_modes": ["unified"]}
    watcher.run_aligned.side_effect = [failed, {"results": {}, "failed_modes": []}]
    watcher._process_queue(config)
    assert watcher._NEXT_ATTEMPT_AT == 1000
    monkeypatch.setattr(watcher.time, "monotonic", lambda: 999)
    watcher._process_queue(config)
    assert watcher.run_aligned.call_count == 1
    monkeypatch.setattr(watcher.time, "monotonic", lambda: 1000)
    watcher._process_queue(config)
    assert watcher.run_aligned.call_count == 2
    assert watcher.run_aligned.call_args.args[0] == "WEGE3"
    assert "fila pausada por 900s" in caplog.text
    assert first.exists() and second.exists()


def test_estado_corrompido_nao_impede_demais_itens(config, monkeypatch, caplog):
    trigger(config, "ABEV3")
    trigger(config, "WEGE3")
    monkeypatch.setattr(watcher, "load_event_context", lambda *args: {"token": "atual"})
    monkeypatch.setattr(watcher, "active_event", lambda context: False)
    path = watcher.aligned_job_path(config, "ABEV3")
    path.parent.mkdir(parents=True)
    path.write_text("{", encoding="utf-8")
    watcher._process_queue(config)
    assert "item preservado" in caplog.text
    assert watcher.run_aligned.call_args.args[0] == "WEGE3"


def test_detecta_mudanca_de_evento_no_estado_unico(config, monkeypatch):
    path = watcher.aligned_job_path(config, "WEGE3")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"event_state": "anterior"}), encoding="utf-8")
    monkeypatch.setattr(watcher, "event_token", lambda context: context["token"])
    assert watcher._calendar_changed(config, "WEGE3", {"token": "atual"})
    assert not watcher._calendar_changed(config, "WEGE3", {"token": "anterior"})
