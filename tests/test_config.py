"""Testes para src/b3_core/config.py."""
import os
from unittest.mock import patch


def test_exemplo_minimo_ollama_sem_modelo_ou_credenciais():
    from pathlib import Path
    from dotenv import dotenv_values
    from b3_core.config import load_config

    example = dotenv_values(Path(__file__).resolve().parents[1] / ".env.example",
                            interpolate=False)
    assert example == {"OLLAMA_URL_BASE": "", "LLM_MODEL": "", "LLM_API_KEY": ""}
    with patch.dict(os.environ, example, clear=True):
        config = load_config()
    assert config.openai_url_base == config.ollama_url_base == config.llm_model == ""
    assert config.queue_dir == "queue"
    assert config.raw_dir == os.path.join("data", "raw")
    assert config.db_path == os.path.join("data", "duckdb", "b3_fundamentals.duckdb")


def test_config_preserva_cache_fundamentus_sem_configuracao_mcp():
    from b3_core.config import load_config

    with patch.dict(os.environ, {
        "AUTH_TOKEN": "legado", "CACHE_TYPE": "memory", "PRICE_TTL": "900",
        "FUND_TTL": "3600",
    }, clear=True):
        config = load_config()
    assert config.fund_ttl == 3600
    assert not any(hasattr(config, name) for name in ("auth_token", "cache_type", "price_ttl"))


def test_load_config_queue_defaults():
    """load_config deve retornar defaults de queue quando env vars ausentes."""
    import sys
    sys.path.insert(0, "src")
    from b3_core.config import load_config

    with patch.dict(os.environ, {}, clear=False):
        env = {k: v for k, v in os.environ.items()
               if k not in ("QUEUE_DIR", "REPORT_MIN_AGE_HOURS", "QUEUE_POLL_SECONDS", "QUEUE_MAX_TRIGGER_AGE_HOURS", "REPORT_HISTORY_N", "QUEUE_REQUEST_INTERVAL_SECONDS", "QUEUE_ERROR_COOLDOWN_SECONDS")}
        with patch.dict(os.environ, env, clear=True):
            config = load_config()

    assert config.queue_dir == "queue"
    assert config.report_min_age_hours == 24.0
    assert config.queue_poll_seconds == 60
    assert config.queue_max_trigger_age_hours == 24.0
    assert config.queue_request_interval_seconds == 60
    assert config.queue_error_cooldown_seconds == 900


def test_load_config_llm_variaveis_compartilhadas():
    from b3_core.config import load_config

    with patch.dict(os.environ, {
        "LLM_API_KEY": "chave", "LLM_MODEL": "modelo-simulado",
        "OLLAMA_URL_BASE": "http://localhost:11434", "OPENAI_URL_BASE": "",
    }, clear=True):
        config = load_config()
    assert config.llm_api_key == "chave"
    assert config.llm_model == "modelo-simulado"
    assert config.ollama_url_base == "http://localhost:11434"
    assert config.openai_url_base == ""


def test_config_sem_llm_permite_fluxos_sem_modelo():
    from b3_core.config import load_config

    with patch.dict(os.environ, {}, clear=True):
        config = load_config()
    assert config.llm_model == ""
    assert config.openai_url_base == config.ollama_url_base == ""


def test_modelo_legado_nao_define_modelo_padrao():
    from b3_core.config import load_config

    with patch.dict(os.environ, {"OPENAI_MODEL_NAME": "modelo-legado"}, clear=True):
        assert load_config().llm_model == ""


def test_load_config_queue_from_env():
    """load_config deve ler queue vars do ambiente."""
    import sys
    sys.path.insert(0, "src")
    from b3_core.config import load_config

    with patch.dict(os.environ, {
        "QUEUE_DIR": "/tmp/myqueue",
        "REPORT_MIN_AGE_HOURS": "48",
        "QUEUE_POLL_SECONDS": "30",
        "QUEUE_MAX_TRIGGER_AGE_HOURS": "12",
        "QUEUE_REQUEST_INTERVAL_SECONDS": "120",
        "QUEUE_ERROR_COOLDOWN_SECONDS": "1800",
    }):
        config = load_config()

    assert config.queue_dir == "/tmp/myqueue"
    assert config.report_min_age_hours == 48.0
    assert config.queue_poll_seconds == 30
    assert config.queue_max_trigger_age_hours == 12.0
    assert config.queue_request_interval_seconds == 120
    assert config.queue_error_cooldown_seconds == 1800







def test_config_ignora_historico_do_fluxo_removido():
    from b3_core.config import load_config

    with patch.dict(os.environ, {"REPORT_HISTORY_N": "last_month"}, clear=True):
        assert not hasattr(load_config(), "report_history_n")
