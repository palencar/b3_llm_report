"""Testes para src/b3_core/config.py."""
import os
from unittest.mock import patch


def test_load_config_queue_defaults():
    """load_config deve retornar defaults de queue quando env vars ausentes."""
    import sys
    sys.path.insert(0, "src")
    from b3_core.config import load_config

    with patch.dict(os.environ, {}, clear=False):
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
