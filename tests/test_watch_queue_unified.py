from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock

import pytest

import watch_queue as watcher


@pytest.fixture
def config(tmp_path, monkeypatch):
    queue = tmp_path / "queue"
    queue.mkdir()
    (queue / "WEGE3").touch()
    monkeypatch.setattr(watcher, "REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(watcher, "_NEXT_ATTEMPT_AT", 0)
    monkeypatch.setattr(watcher, "_LAST_ATTEMPTED_ENTRY", None)
    monkeypatch.setattr(watcher, "load_event_context", Mock(return_value=None))
    monkeypatch.setattr(watcher, "load_dotenv", Mock())
    return SimpleNamespace(queue_dir=str(queue), raw_dir=str(tmp_path / "raw"),
                           report_min_age_hours=24, queue_max_trigger_age_hours=24,
                           queue_request_interval_seconds=60, queue_error_cooldown_seconds=900,
                           queue_poll_seconds=60, llm_model="simulado", llm_api_key="",
                           ollama_url_base="http://simulado", openai_url_base="")


@pytest.mark.parametrize("failed,delay", [([], 60), (["unified"], 900)])
def test_unificado_preserva_pacing_e_imprime_uma_vez(config, monkeypatch, capsys, failed, delay):
    monkeypatch.setattr(watcher.time, "monotonic", lambda: 100)
    monkeypatch.setattr(watcher, "should_run_report", Mock(return_value=(True, "simulado")))
    run = Mock(return_value={"results": {"unified": {}}, "failed_modes": failed})
    monkeypatch.setattr(watcher, "run_report", run)
    monkeypatch.setattr(watcher, "format_report_markdown", lambda result: "Relatorio unico.")
    watcher._process_queue(config, structured_output=True)
    watcher._process_queue(config)
    run.assert_called_once_with("WEGE3", config=config, trigger_mtime=(Path(config.queue_dir) / "WEGE3").stat().st_mtime,
        reports_dir=watcher.REPORTS_DIR, structured_output=True)
    assert watcher._NEXT_ATTEMPT_AT == 100 + delay
    assert capsys.readouterr().out.count("Relatorio unico.") == 1


def test_controle_invalido_preserva_item_sem_chamar_modelo(config, monkeypatch, caplog):
    monkeypatch.setattr(watcher, "should_run_report", Mock(side_effect=ValueError("Controle invalido")))
    run = Mock(side_effect=AssertionError("Nao executar."))
    monkeypatch.setattr(watcher, "run_report", run)
    watcher._process_queue(config)
    run.assert_not_called()
    assert "item preservado" in caplog.text


@pytest.mark.parametrize("flags", [[], ["--unified"]])
def test_cli_unificado_mantem_argumentos(config, monkeypatch, flags):
    monkeypatch.setattr(watcher, "load_config", lambda: config)
    process = Mock(side_effect=KeyboardInterrupt)
    monkeypatch.setattr(watcher, "_process_queue", process)
    with pytest.raises(KeyboardInterrupt):
        watcher.main([*flags, "--structured-output", "on"])
    process.assert_called_once_with(config, structured_output=True)


@pytest.mark.parametrize("args", [["--decision-model", "modelo"], ["--with-report"],
                                   ["--structured-output", "invalido"]])
def test_cli_rejeita_modos_removidos_antes_do_ambiente(config, args):
    with pytest.raises(SystemExit) as exc:
        watcher.main(args)
    assert exc.value.code == 2
    watcher.load_dotenv.assert_not_called()
