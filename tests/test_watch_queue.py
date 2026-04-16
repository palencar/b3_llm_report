"""Testes para watch_queue.py."""
import os
import time
from dataclasses import dataclass
from unittest.mock import patch

import pytest


@dataclass(frozen=True)
class _FakeConfig:
    queue_dir: str
    report_min_age_hours: float
    queue_poll_seconds: int = 60
    openai_api_key: str = ""
    openai_url_base: str = ""
    openai_model_name: str = ""
    crawl4ai_model_api_key: str = ""
    crawl4ai_model_provider: str = ""
    crawl4ai_model_url_base: str = ""
    db_path: str = ""
    snapshot_dir: str = ""
    raw_dir: str = ""
    brapi_key: str = ""
    brapi_base_url: str = ""
    auth_token: str = ""
    cache_type: str = ""
    fund_ttl: int = 86400
    price_ttl: int = 900
    log_level: str = "INFO"


import sys
sys.path.insert(0, ".")

from watch_queue import _process_queue, _should_generate

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
    _touch(os.path.join(config.queue_dir, "PETR4"))

    with patch(_PATCH_RUN_REPORT) as mock_report:
        with patch("watch_queue.REPORTS_DIR", reports_dir):
            _process_queue(config)

    mock_report.assert_called_once_with("PETR4")


def test_skip_relatorio_atualizado(tmp_path):
    """Relatório gerado depois do trigger na fila → run_report não chamado."""
    config = _make_config(tmp_path, min_age_hours=24.0)
    reports_dir = str(tmp_path / "reports")
    os.makedirs(reports_dir, exist_ok=True)
    now = time.time()
    _touch(os.path.join(reports_dir, "VALE3.md"), mtime=now)
    _touch(os.path.join(config.queue_dir, "VALE3"), mtime=now - 3600)  # fila mais antiga

    with patch(_PATCH_RUN_REPORT) as mock_report:
        with patch("watch_queue.REPORTS_DIR", reports_dir):
            _process_queue(config)

    mock_report.assert_not_called()


def test_gera_relatorio_quando_fila_mais_nova(tmp_path):
    """Fila tocada depois do relatório E relatório velho → run_report chamado."""
    config = _make_config(tmp_path, min_age_hours=1.0)
    reports_dir = str(tmp_path / "reports")
    os.makedirs(reports_dir, exist_ok=True)
    now = time.time()
    _touch(os.path.join(reports_dir, "ITUB4.md"), mtime=now - 7200)  # relatório 2h atrás
    _touch(os.path.join(config.queue_dir, "ITUB4"), mtime=now)       # fila = agora

    with patch(_PATCH_RUN_REPORT) as mock_report:
        with patch("watch_queue.REPORTS_DIR", reports_dir):
            _process_queue(config)

    mock_report.assert_called_once_with("ITUB4")


def test_erro_run_report_nao_trava_loop(tmp_path):
    """run_report lança exceção → sem propagação."""
    config = _make_config(tmp_path)
    reports_dir = str(tmp_path / "reports")
    os.makedirs(reports_dir, exist_ok=True)
    _touch(os.path.join(config.queue_dir, "BBAS3"))

    with patch(_PATCH_RUN_REPORT, side_effect=Exception("LLM timeout")):
        with patch("watch_queue.REPORTS_DIR", reports_dir):
            _process_queue(config)  # não deve propagar


def test_ticker_invalido_ignorado(tmp_path):
    """Nome de arquivo inválido → ignorado sem chamar run_report."""
    config = _make_config(tmp_path)
    reports_dir = str(tmp_path / "reports")
    os.makedirs(reports_dir, exist_ok=True)
    _touch(os.path.join(config.queue_dir, "TICKER!@#"))

    with patch(_PATCH_RUN_REPORT) as mock_report:
        with patch("watch_queue.REPORTS_DIR", reports_dir):
            _process_queue(config)

    mock_report.assert_not_called()


def test_multiplos_tickers(tmp_path):
    """Dois tickers na fila → ambos processados independentemente."""
    config = _make_config(tmp_path)
    reports_dir = str(tmp_path / "reports")
    os.makedirs(reports_dir, exist_ok=True)
    for ticker in ("WEGE3", "EGIE3"):
        _touch(os.path.join(config.queue_dir, ticker))

    called = []
    with patch(_PATCH_RUN_REPORT, side_effect=lambda t: called.append(t)):
        with patch("watch_queue.REPORTS_DIR", reports_dir):
            _process_queue(config)

    assert set(called) == {"WEGE3", "EGIE3"}
