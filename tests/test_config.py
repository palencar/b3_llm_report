"""Testes para src/b3_core/config.py."""
import os
from unittest.mock import patch


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
    assert config.report_history_n == 4
    assert config.queue_request_interval_seconds == 60
    assert config.queue_error_cooldown_seconds == 900


def test_load_config_llm_variaveis_compartilhadas():
    from b3_core.config import load_config

    with patch.dict(os.environ, {
        "LLM_API_KEY": "chave", "LLM_MODEL": "qwen3.6:80k",
        "OLLAMA_URL_BASE": "http://localhost:11434", "OPENAI_URL_BASE": "",
    }, clear=True):
        config = load_config()
    assert config.llm_api_key == "chave"
    assert config.llm_model == "qwen3.6:80k"
    assert config.ollama_url_base == "http://localhost:11434"
    assert config.openai_url_base == ""


def test_config_sem_llm_permite_fluxos_sem_modelo():
    from b3_core.config import load_config

    with patch.dict(os.environ, {}, clear=True):
        config = load_config()
    assert config.llm_model == ""
    assert config.openai_url_base == config.ollama_url_base == ""


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
        "REPORT_HISTORY_N": "6",
        "QUEUE_REQUEST_INTERVAL_SECONDS": "120",
        "QUEUE_ERROR_COOLDOWN_SECONDS": "1800",
    }):
        config = load_config()

    assert config.queue_dir == "/tmp/myqueue"
    assert config.report_min_age_hours == 48.0
    assert config.queue_poll_seconds == 30
    assert config.queue_max_trigger_age_hours == 12.0
    assert config.report_history_n == 6
    assert config.queue_request_interval_seconds == 120
    assert config.queue_error_cooldown_seconds == 1800


def test_load_config_report_history_n_invalido_faz_fallback():
    """load_config deve usar default para REPORT_HISTORY_N invalido."""
    import sys
    sys.path.insert(0, "src")
    from b3_core.config import load_config

    with patch.dict(os.environ, {"REPORT_HISTORY_N": "0"}):
        config = load_config()
    assert config.report_history_n == 4

def test_load_config_report_history_n_last_month():
    """load_config deve aceitar 'last_month' para REPORT_HISTORY_N."""
    import sys, os
    from b3_core.config import load_config

    with patch.dict(os.environ, {"REPORT_HISTORY_N": "last_month"}):
        config = load_config()
        assert config.report_history_n == "last_month"

    with patch.dict(os.environ, {"REPORT_HISTORY_N": "LAST_MONTH"}):
        config = load_config()
        assert config.report_history_n == "last_month"


def test_parse_history_n_last_month_case_insensitive():
    """_parse_history_n deve ser case-insensitive para last_month."""
    import sys, os
    from b3_core.config import _parse_history_n
    for val in ("last_month", "LAST_MONTH", "Last_Month"):
        with patch.dict(os.environ, {"_TEST_PHN": val}):
            assert _parse_history_n("_TEST_PHN", 4) == "last_month"
    # numeric value should still parse normally
    with patch.dict(os.environ, {"_TEST_PHN": "10"}):
            assert _parse_history_n("_TEST_PHN", 4) == 10
