"""Testes para watch_queue.py."""
import os
import time
from dataclasses import dataclass
from unittest.mock import patch, MagicMock

import pytest


# Config mínimo para testes — sem precisar de .env
@dataclass(frozen=True)
class _FakeConfig:
    queue_dir: str
    report_min_age_hours: float
    queue_poll_seconds: int = 60
    # campos obrigatórios do Config real (não usados pelo watcher)
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
sys.path.insert(0, ".")   # para importar watch_queue da raiz

from watch_queue import _process_queue


_PATCH_RUN_REPORT = "watch_queue.run_report"


def _make_config(tmp_path, min_age_hours=24.0):
    queue_dir = str(tmp_path / "queue")
    os.makedirs(queue_dir, exist_ok=True)
    return _FakeConfig(queue_dir=queue_dir, report_min_age_hours=min_age_hours)


def test_gera_relatorio_se_ausente(tmp_path):
    """Sem relatório existente → run_report chamado, arquivo de fila removido."""
    config = _make_config(tmp_path)
    reports_dir = str(tmp_path / "reports")
    os.makedirs(reports_dir, exist_ok=True)

    # Criar trigger na fila
    trigger = os.path.join(config.queue_dir, "PETR4")
    open(trigger, "w").close()

    with patch(_PATCH_RUN_REPORT) as mock_report:
        with patch("watch_queue.REPORTS_DIR", reports_dir):
            _process_queue(config)

    mock_report.assert_called_once_with("PETR4")
    assert not os.path.exists(trigger)


def test_skip_relatorio_recente(tmp_path):
    """Relatório com mtime < report_min_age_hours → run_report não chamado."""
    config = _make_config(tmp_path, min_age_hours=24.0)
    reports_dir = str(tmp_path / "reports")
    os.makedirs(reports_dir, exist_ok=True)

    # Criar relatório recente (agora)
    report = os.path.join(reports_dir, "VALE3.md")
    open(report, "w").close()  # mtime = agora → age ≈ 0h < 24h

    trigger = os.path.join(config.queue_dir, "VALE3")
    open(trigger, "w").close()

    with patch(_PATCH_RUN_REPORT) as mock_report:
        with patch("watch_queue.REPORTS_DIR", reports_dir):
            _process_queue(config)

    mock_report.assert_not_called()
    assert not os.path.exists(trigger)


def test_gera_relatorio_antigo(tmp_path):
    """Relatório com mtime > report_min_age_hours → run_report chamado."""
    config = _make_config(tmp_path, min_age_hours=1.0)
    reports_dir = str(tmp_path / "reports")
    os.makedirs(reports_dir, exist_ok=True)

    # Criar relatório antigo (mtime = 2 horas atrás)
    report = os.path.join(reports_dir, "ITUB4.md")
    open(report, "w").close()
    old_mtime = time.time() - 7200  # 2 horas atrás
    os.utime(report, (old_mtime, old_mtime))

    trigger = os.path.join(config.queue_dir, "ITUB4")
    open(trigger, "w").close()

    with patch(_PATCH_RUN_REPORT) as mock_report:
        with patch("watch_queue.REPORTS_DIR", reports_dir):
            _process_queue(config)

    mock_report.assert_called_once_with("ITUB4")
    assert not os.path.exists(trigger)


def test_erro_run_report_nao_trava_loop(tmp_path):
    """run_report lança exceção → arquivo de fila removido, sem propagação."""
    config = _make_config(tmp_path)
    reports_dir = str(tmp_path / "reports")
    os.makedirs(reports_dir, exist_ok=True)

    trigger = os.path.join(config.queue_dir, "BBAS3")
    open(trigger, "w").close()

    with patch(_PATCH_RUN_REPORT, side_effect=Exception("LLM timeout")):
        with patch("watch_queue.REPORTS_DIR", reports_dir):
            _process_queue(config)  # não deve propagar

    assert not os.path.exists(trigger)


def test_ticker_invalido_removido(tmp_path):
    """Nome de arquivo inválido → removido sem chamar run_report."""
    config = _make_config(tmp_path)
    reports_dir = str(tmp_path / "reports")
    os.makedirs(reports_dir, exist_ok=True)

    trigger = os.path.join(config.queue_dir, "TICKER!@#")
    open(trigger, "w").close()

    with patch(_PATCH_RUN_REPORT) as mock_report:
        with patch("watch_queue.REPORTS_DIR", reports_dir):
            _process_queue(config)

    mock_report.assert_not_called()
    assert not os.path.exists(trigger)


def test_multiplos_tickers(tmp_path):
    """Dois tickers na fila → ambos processados independentemente."""
    config = _make_config(tmp_path)
    reports_dir = str(tmp_path / "reports")
    os.makedirs(reports_dir, exist_ok=True)

    for ticker in ("WEGE3", "EGIE3"):
        open(os.path.join(config.queue_dir, ticker), "w").close()

    called = []
    with patch(_PATCH_RUN_REPORT, side_effect=lambda t: called.append(t)):
        with patch("watch_queue.REPORTS_DIR", reports_dir):
            _process_queue(config)

    assert set(called) == {"WEGE3", "EGIE3"}
    assert not os.path.exists(os.path.join(config.queue_dir, "WEGE3"))
    assert not os.path.exists(os.path.join(config.queue_dir, "EGIE3"))
