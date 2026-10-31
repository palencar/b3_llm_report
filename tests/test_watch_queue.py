"""Testes para watch_queue.py."""
import logging
import os
import sys
import time
import types
from dataclasses import dataclass
from unittest.mock import patch

import pytest


@dataclass(frozen=True)
class _FakeConfig:
    queue_dir: str
    report_min_age_hours: float
    queue_poll_seconds: int = 60
    queue_max_trigger_age_hours: float = 24.0
    queue_request_interval_seconds: int = 60
    queue_error_cooldown_seconds: int = 900
    llm_api_key: str = ""
    openai_url_base: str = ""
    ollama_url_base: str = ""
    llm_model: str = ""
    db_path: str = ""
    snapshot_dir: str = ""
    raw_dir: str = ""
    brapi_key: str = ""
    brapi_base_url: str = ""
    fund_ttl: int = 86400
    log_level: str = "INFO"


sys.path.insert(0, ".")

if "openai" not in sys.modules:
    openai_stub = types.ModuleType("openai")
    openai_stub.OpenAI = object
    sys.modules["openai"] = openai_stub


if "yfinance" not in sys.modules:
    yfinance_stub = types.ModuleType("yfinance")
    yfinance_stub.Ticker = object
    sys.modules["yfinance"] = yfinance_stub

from watch_queue import _process_queue, _should_generate


@pytest.fixture(autouse=True)
def _reset_queue_pacing(monkeypatch):
    monkeypatch.setattr("watch_queue._NEXT_ATTEMPT_AT", 0.0)
    monkeypatch.setattr("watch_queue._LAST_ATTEMPTED_ENTRY", None)

_PATCH_RUN_REPORT = "watch_queue.run_report"


def _make_config(tmp_path, min_age_hours=24.0):
    queue_dir = str(tmp_path / "queue")
    os.makedirs(queue_dir, exist_ok=True)
    return _FakeConfig(queue_dir=queue_dir, report_min_age_hours=min_age_hours)


def _touch(path, mtime=None):
    open(path, "w").close()
    if mtime is not None:
        os.utime(path, (mtime, mtime))


# --- testes de _should_generate ---

def test_should_generate_sem_relatorio(tmp_path):
    """Sem relatório → deve gerar."""
    with patch("watch_queue.REPORTS_DIR", str(tmp_path / "reports")):
        ok, reason = _should_generate("PETR4", time.time(), 24.0)
    assert ok
    assert "absent" in reason


def test_should_generate_relatorio_mais_novo_que_fila(tmp_path):
    """Relatório gerado depois do trigger → não deve gerar."""
    reports_dir = str(tmp_path / "reports")
    os.makedirs(reports_dir, exist_ok=True)
    now = time.time()
    _touch(os.path.join(reports_dir, "VALE3.md"), mtime=now)  # relatório = agora
    queue_mtime = now - 3600  # fila = 1h atrás

    with patch("watch_queue.REPORTS_DIR", reports_dir):
        ok, reason = _should_generate("VALE3", queue_mtime, 24.0)
    assert not ok
    assert "newer than queue trigger" in reason


def test_should_generate_reconhece_relatorio_legado_sem_extensao(tmp_path):
    """Arquivo legado sem extensão deve contar como relatório existente."""
    reports_dir = str(tmp_path / "reports")
    os.makedirs(reports_dir, exist_ok=True)
    now = time.time()
    _touch(os.path.join(reports_dir, "LREN3"), mtime=now)
    queue_mtime = now - 3600

    with patch("watch_queue.REPORTS_DIR", reports_dir):
        ok, reason = _should_generate("LREN3", queue_mtime, 24.0)
    assert not ok
    assert "newer than queue trigger" in reason


def test_should_generate_fila_mais_nova_mas_relatorio_fresco(tmp_path):
    """Fila mais nova que relatório, mas relatório gerado há menos de min_age → não gerar."""
    reports_dir = str(tmp_path / "reports")
    os.makedirs(reports_dir, exist_ok=True)
    now = time.time()
    _touch(os.path.join(reports_dir, "ITUB4.md"), mtime=now - 1800)  # relatório = 30min atrás
    queue_mtime = now  # fila = agora (mais nova que relatório)

    with patch("watch_queue.REPORTS_DIR", reports_dir):
        ok, reason = _should_generate("ITUB4", queue_mtime, 24.0)
    assert not ok
    assert "too recent" in reason


def test_should_generate_fila_mais_nova_e_relatorio_velho(tmp_path):
    """Fila mais nova que relatório E relatório antigo o suficiente → deve gerar."""
    reports_dir = str(tmp_path / "reports")
    os.makedirs(reports_dir, exist_ok=True)
    now = time.time()
    _touch(os.path.join(reports_dir, "WEGE3.md"), mtime=now - 7200)  # relatório = 2h atrás
    queue_mtime = now  # fila = agora (mais nova que relatório)

    with patch("watch_queue.REPORTS_DIR", reports_dir):
        ok, reason = _should_generate("WEGE3", queue_mtime, 1.0)
    assert ok
    assert "trigger newer than report" in reason


# --- testes de _process_queue ---

def test_gera_relatorio_se_ausente(tmp_path):
    """Sem relatório existente → run_report chamado."""
    config = _make_config(tmp_path)
    reports_dir = str(tmp_path / "reports")
    os.makedirs(reports_dir, exist_ok=True)
    trigger = os.path.join(config.queue_dir, "PETR4")
    _touch(trigger)

    with patch(_PATCH_RUN_REPORT) as mock_report:
        with patch("watch_queue.REPORTS_DIR", reports_dir):
            _process_queue(config)

    mock_report.assert_called_once_with("PETR4")
    assert os.path.exists(trigger)


def test_skip_relatorio_atualizado(tmp_path):
    """Relatório gerado depois do trigger na fila → run_report não chamado."""
    config = _make_config(tmp_path, min_age_hours=24.0)
    reports_dir = str(tmp_path / "reports")
    os.makedirs(reports_dir, exist_ok=True)
    now = time.time()
    _touch(os.path.join(reports_dir, "VALE3.md"), mtime=now)
    trigger = os.path.join(config.queue_dir, "VALE3")
    _touch(trigger, mtime=now - 3600)  # fila mais antiga

    with patch(_PATCH_RUN_REPORT) as mock_report:
        with patch("watch_queue.REPORTS_DIR", reports_dir):
            _process_queue(config)

    mock_report.assert_not_called()
    assert os.path.exists(trigger)


def test_skip_relatorio_atualizado_loga_uma_vez_por_trigger(tmp_path, caplog):
    """Skip repetido no mesmo trigger não deve poluir o log a cada polling."""
    config = _make_config(tmp_path, min_age_hours=24.0)
    reports_dir = str(tmp_path / "reports")
    os.makedirs(reports_dir, exist_ok=True)
    now = time.time()
    _touch(os.path.join(reports_dir, "ANIM3.md"), mtime=now)
    trigger = os.path.join(config.queue_dir, "ANIM3")
    _touch(trigger, mtime=now - 3600)

    with patch(_PATCH_RUN_REPORT) as mock_report:
        with patch("watch_queue.REPORTS_DIR", reports_dir):
            with caplog.at_level(logging.INFO):
                _process_queue(config)
                _process_queue(config)
                _touch(trigger, mtime=now - 1800)
                _process_queue(config)

    mock_report.assert_not_called()
    skipped = [
        record.message
        for record in caplog.records
        if record.message.startswith("skipped ANIM3")
    ]
    assert len(skipped) == 2
    assert os.path.exists(trigger)


def test_skip_relatorio_legado_sem_extensao(tmp_path):
    """Arquivo legado sem extensão deve impedir geração desnecessária."""
    config = _make_config(tmp_path, min_age_hours=24.0)
    reports_dir = str(tmp_path / "reports")
    os.makedirs(reports_dir, exist_ok=True)
    now = time.time()
    _touch(os.path.join(reports_dir, "LREN3"), mtime=now)
    trigger = os.path.join(config.queue_dir, "LREN3")
    _touch(trigger, mtime=now - 3600)

    with patch(_PATCH_RUN_REPORT) as mock_report:
        with patch("watch_queue.REPORTS_DIR", reports_dir):
            _process_queue(config)

    mock_report.assert_not_called()
    assert os.path.exists(trigger)


def test_gera_relatorio_quando_fila_mais_nova(tmp_path):
    """Fila tocada depois do relatório E relatório velho → run_report chamado."""
    config = _make_config(tmp_path, min_age_hours=1.0)
    reports_dir = str(tmp_path / "reports")
    os.makedirs(reports_dir, exist_ok=True)
    now = time.time()
    _touch(os.path.join(reports_dir, "ITUB4.md"), mtime=now - 7200)  # relatório 2h atrás
    trigger = os.path.join(config.queue_dir, "ITUB4")
    _touch(trigger, mtime=now)       # fila = agora

    with patch(_PATCH_RUN_REPORT) as mock_report:
        with patch("watch_queue.REPORTS_DIR", reports_dir):
            _process_queue(config)

    mock_report.assert_called_once_with("ITUB4")
    assert os.path.exists(trigger)


def test_erro_run_report_nao_trava_loop(tmp_path):
    """run_report lança exceção → sem propagação."""
    config = _make_config(tmp_path)
    reports_dir = str(tmp_path / "reports")
    os.makedirs(reports_dir, exist_ok=True)
    trigger = os.path.join(config.queue_dir, "BBAS3")
    _touch(trigger)

    with patch(_PATCH_RUN_REPORT, side_effect=Exception("LLM timeout")):
        with patch("watch_queue.REPORTS_DIR", reports_dir):
            _process_queue(config)  # não deve propagar
    assert os.path.exists(trigger)


def test_ticker_invalido_ignorado(tmp_path):
    """Nome de arquivo inválido → ignorado sem chamar run_report."""
    config = _make_config(tmp_path)
    reports_dir = str(tmp_path / "reports")
    os.makedirs(reports_dir, exist_ok=True)
    trigger = os.path.join(config.queue_dir, "TICKER!@#")
    _touch(trigger)

    with patch(_PATCH_RUN_REPORT) as mock_report:
        with patch("watch_queue.REPORTS_DIR", reports_dir):
            _process_queue(config)

    mock_report.assert_not_called()
    assert os.path.exists(trigger)


def test_multiplos_tickers(tmp_path):
    """Dois tickers sao espacados mesmo se houver novas varreduras."""
    config = _make_config(tmp_path)
    reports_dir = str(tmp_path / "reports")
    os.makedirs(reports_dir, exist_ok=True)
    triggers = []
    for ticker in ("WEGE3", "EGIE3"):
        trigger = os.path.join(config.queue_dir, ticker)
        _touch(trigger)
        triggers.append(trigger)

    called = []
    with patch(_PATCH_RUN_REPORT, side_effect=lambda t: called.append(t)), \
         patch("watch_queue.time.monotonic", return_value=100.0) as clock:
        with patch("watch_queue.REPORTS_DIR", reports_dir):
            _process_queue(config)
            assert len(called) == 1
            clock.return_value = 159.0
            _process_queue(config)
            assert len(called) == 1
            clock.return_value = 160.0
            _process_queue(config)

    assert set(called) == {"WEGE3", "EGIE3"}
    assert all(os.path.exists(trigger) for trigger in triggers)


def test_erro_pausa_fila_e_retoma_no_proximo_ticker(tmp_path, caplog):
    config = _make_config(tmp_path)
    for ticker in ("UGPA3", "VIVT3"):
        _touch(os.path.join(config.queue_dir, ticker))

    with patch("watch_queue.REPORTS_DIR", str(tmp_path / "reports")), \
         patch("watch_queue.time.monotonic", return_value=100.0) as clock, \
         patch(_PATCH_RUN_REPORT, side_effect=[ValueError("resposta Yahoo invalida"), None]) as report:
        _process_queue(config)
        report.assert_called_once_with("UGPA3")
        clock.return_value = 999.0
        _process_queue(config)
        assert report.call_count == 1
        clock.return_value = 1000.0
        _process_queue(config)
        assert report.call_args.args == ("VIVT3",)
        assert report.call_count == 2

    assert "fila pausada por 900s" in caplog.text
    assert os.path.exists(os.path.join(config.queue_dir, "UGPA3"))
    assert os.path.exists(os.path.join(config.queue_dir, "VIVT3"))


def test_ignora_trigger_antigo_por_mtime(tmp_path):
    """Trigger antigo demais deve ser ignorado sem chamar run_report."""
    config = _make_config(tmp_path)
    reports_dir = str(tmp_path / "reports")
    os.makedirs(reports_dir, exist_ok=True)
    now = time.time()
    trigger = os.path.join(config.queue_dir, "PETR4")
    _touch(trigger, mtime=now - 72 * 3600)

    with patch(_PATCH_RUN_REPORT) as mock_report:
        with patch("watch_queue.REPORTS_DIR", reports_dir):
            _process_queue(config)

    mock_report.assert_not_called()
    assert os.path.exists(trigger)
