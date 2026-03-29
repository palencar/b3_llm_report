# Watch Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Criar um script de polling `watch_queue.py` que monitora um diretório de fila, gera relatórios LLM para tickers disparados, e evita regeneração antes de `REPORT_MIN_AGE_HOURS` horas.

**Architecture:** R (ou qualquer processo) cria `queue/TICKER` (arquivo vazio). `watch_queue.py` acorda a cada `QUEUE_POLL_SECONDS`, processa cada arquivo da fila verificando a idade do relatório existente em `reports/`, e remove o arquivo da fila independente do resultado. Config via `Config` dataclass — fácil de containerizar com volume mounts.

**Tech Stack:** Python stdlib (`os`, `time`, `re`, `logging`), `dotenv`, `b3_core.config`, `b3_report.cli.run_report`

---

### Task 1: Adicionar campos de queue ao Config

**Files:**
- Modify: `src/b3_core/config.py`
- Modify: `.env.example`
- Test: `tests/test_config.py` (criar)

- [ ] **Step 1: Escrever o teste (deve falhar)**

Criar `tests/test_config.py`:

```python
"""Testes para src/b3_core/config.py."""
import os
from unittest.mock import patch


def test_load_config_queue_defaults():
    """load_config deve retornar defaults de queue quando env vars ausentes."""
    import sys
    sys.path.insert(0, "src")
    from b3_core.config import load_config

    with patch.dict(os.environ, {}, clear=False):
        # Remover as vars de queue do ambiente para testar defaults
        env = {k: v for k, v in os.environ.items()
               if k not in ("QUEUE_DIR", "REPORT_MIN_AGE_HOURS", "QUEUE_POLL_SECONDS")}
        with patch.dict(os.environ, env, clear=True):
            config = load_config()

    assert config.queue_dir == "queue"
    assert config.report_min_age_hours == 24.0
    assert config.queue_poll_seconds == 60


def test_load_config_queue_from_env():
    """load_config deve ler queue vars do ambiente."""
    import sys
    sys.path.insert(0, "src")
    from b3_core.config import load_config

    with patch.dict(os.environ, {
        "QUEUE_DIR": "/tmp/myqueue",
        "REPORT_MIN_AGE_HOURS": "48",
        "QUEUE_POLL_SECONDS": "30",
    }):
        config = load_config()

    assert config.queue_dir == "/tmp/myqueue"
    assert config.report_min_age_hours == 48.0
    assert config.queue_poll_seconds == 30
```

- [ ] **Step 2: Rodar — confirmar que falha**

```bash
cd /home/paulo/Projetos/b3_llm_report
python -m pytest tests/test_config.py -v
```

Esperado: FAIL — `Config` não tem `queue_dir`.

- [ ] **Step 3: Adicionar campos ao Config**

Em `src/b3_core/config.py`, adicionar os 3 campos ao dataclass e ao `load_config`. O arquivo completo fica:

```python
from dataclasses import dataclass
import os


def _get_env(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    openai_api_key: str
    openai_url_base: str
    openai_model_name: str
    crawl4ai_model_api_key: str
    crawl4ai_model_provider: str
    crawl4ai_model_url_base: str
    db_path: str
    snapshot_dir: str
    raw_dir: str
    brapi_key: str
    brapi_base_url: str
    auth_token: str
    cache_type: str
    fund_ttl: int
    price_ttl: int
    log_level: str
    queue_dir: str
    report_min_age_hours: float
    queue_poll_seconds: int


def load_config() -> Config:
    return Config(
        openai_api_key=_get_env("OPENAI_API_KEY", "api_key"),
        openai_url_base=_get_env("OPENAI_URL_BASE", "http://localhost:11434/v1"),
        openai_model_name=_get_env("OPENAI_MODEL_NAME", "llama3.1"),
        crawl4ai_model_api_key=_get_env("CRAWL4AI_MODEL_API_KEY", "token"),
        crawl4ai_model_provider=_get_env("CRAWL4AI_MODEL_PROVIDER", "ollama/llama3.1:8b-8k"),
        crawl4ai_model_url_base=_get_env("CRAWL4AI_MODEL_URL_BASE", "http://localhost:11434"),
        db_path=_get_env("DB_PATH", os.path.join("data", "duckdb", "b3_fundamentals.duckdb")),
        snapshot_dir=_get_env("SNAPSHOT_DIR", os.path.join("data", "snapshots")),
        raw_dir=_get_env("RAW_DIR", os.path.join("data", "raw")),
        brapi_key=_get_env("BRAPI_KEY", ""),
        brapi_base_url=_get_env("BRAPI_BASE_URL", "https://brapi.dev/api"),
        auth_token=_get_env("AUTH_TOKEN", ""),
        cache_type=_get_env("CACHE_TYPE", "memory"),
        fund_ttl=_get_int("FUND_TTL", 86400),
        price_ttl=_get_int("PRICE_TTL", 900),
        log_level=_get_env("LOG_LEVEL", "INFO"),
        queue_dir=_get_env("QUEUE_DIR", "queue"),
        report_min_age_hours=_get_float("REPORT_MIN_AGE_HOURS", 24.0),
        queue_poll_seconds=_get_int("QUEUE_POLL_SECONDS", 60),
    )
```

- [ ] **Step 4: Atualizar `.env.example`**

Adicionar ao final do arquivo:

```
# Queue de relatórios
QUEUE_DIR=queue
REPORT_MIN_AGE_HOURS=24
QUEUE_POLL_SECONDS=60
```

- [ ] **Step 5: Rodar — confirmar que passa**

```bash
python -m pytest tests/test_config.py -v
```

Esperado: 2 PASSes.

- [ ] **Step 6: Rodar suite completa — sem regressões**

```bash
python -m pytest tests/ -q
```

Esperado: todos passando.

- [ ] **Step 7: Commit**

```bash
git add src/b3_core/config.py .env.example tests/test_config.py
git commit -m "feat: adiciona queue_dir, report_min_age_hours, queue_poll_seconds ao Config"
```

---

### Task 2: Implementar `watch_queue.py` (TDD)

**Files:**
- Create: `tests/test_watch_queue.py`
- Create: `watch_queue.py`

- [ ] **Step 1: Criar `tests/test_watch_queue.py` com os 6 testes**

```python
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
```

- [ ] **Step 2: Rodar — confirmar que falha**

```bash
python -m pytest tests/test_watch_queue.py -v
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'watch_queue'`.

- [ ] **Step 3: Criar `watch_queue.py` na raiz do projeto**

```python
"""Watch queue: monitora queue_dir e gera relatórios LLM por ticker."""
import logging
import os
import re
import sys
import time

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from dotenv import load_dotenv

from b3_core.config import load_config
from b3_report.cli import run_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
_logger = logging.getLogger(__name__)

REPORTS_DIR = "reports"
_TICKER_RE = re.compile(r"^[A-Z0-9]{3,6}$")


def _report_age_hours(ticker: str) -> float | None:
    """Return age of reports/TICKER.md in hours, or None if it does not exist."""
    path = os.path.join(REPORTS_DIR, f"{ticker}.md")
    if not os.path.exists(path):
        return None
    return (time.time() - os.path.getmtime(path)) / 3600


def _process_queue(config) -> None:
    """Process all files currently in config.queue_dir."""
    try:
        entries = os.listdir(config.queue_dir)
    except OSError:
        return

    for name in entries:
        filepath = os.path.join(config.queue_dir, name)
        ticker = name.upper()
        try:
            if not _TICKER_RE.match(ticker):
                _logger.warning("invalid ticker in queue, skipping: %s", name)
                continue

            age = _report_age_hours(ticker)
            if age is not None and age < config.report_min_age_hours:
                _logger.info("skipped %s (report age: %.1fh)", ticker, age)
                continue

            _logger.info("generating report for %s", ticker)
            run_report(ticker)
            _logger.info("generated %s", ticker)

        except Exception:
            _logger.exception("error processing ticker %s", ticker)
        finally:
            try:
                os.remove(filepath)
            except OSError:
                _logger.warning("could not remove queue file: %s", filepath)


def main() -> None:
    load_dotenv()
    config = load_config()
    os.makedirs(config.queue_dir, exist_ok=True)
    os.makedirs(REPORTS_DIR, exist_ok=True)
    _logger.info(
        "watch_queue started: queue_dir=%s poll=%ds min_age=%.1fh",
        config.queue_dir,
        config.queue_poll_seconds,
        config.report_min_age_hours,
    )
    while True:
        _process_queue(config)
        time.sleep(config.queue_poll_seconds)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Rodar — confirmar que passa**

```bash
python -m pytest tests/test_watch_queue.py -v
```

Esperado: 6 PASSes.

- [ ] **Step 5: Rodar suite completa — sem regressões**

```bash
python -m pytest tests/ -q
```

Esperado: todos passando.

- [ ] **Step 6: Commit**

```bash
git add watch_queue.py tests/test_watch_queue.py
git commit -m "feat: watch_queue.py — polling de fila de arquivos para geração de relatórios"
```
