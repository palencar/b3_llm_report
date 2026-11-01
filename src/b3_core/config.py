from dataclasses import dataclass
import logging
import os

_logger = logging.getLogger(__name__)


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
        _logger.warning(
            "Valor invalido para %s=%r; usando padrao %s.",
            name,
            value,
            default,
        )
        return default


def _get_positive_int(name: str, default: int) -> int:
    value = _get_int(name, default)
    if value < 1:
        _logger.warning(
            "Valor fora do contrato para %s=%r; usando padrao %s.",
            name,
            os.getenv(name),
            default,
        )
        return default
    return value


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
    llm_api_key: str
    openai_url_base: str
    ollama_url_base: str
    llm_model: str
    db_path: str
    snapshot_dir: str
    raw_dir: str
    brapi_key: str
    brapi_base_url: str
    fund_ttl: int
    log_level: str
    queue_dir: str
    report_min_age_hours: float
    queue_poll_seconds: int
    queue_max_trigger_age_hours: float
    queue_request_interval_seconds: int = 60
    queue_error_cooldown_seconds: int = 900
    corporate_events_file: str = ""


def load_config() -> Config:
    return Config(
        llm_api_key=_get_env("LLM_API_KEY", ""),
        openai_url_base=_get_env("OPENAI_URL_BASE", "").strip(),
        ollama_url_base=_get_env("OLLAMA_URL_BASE", "").strip(),
        llm_model=_get_env("LLM_MODEL", "").strip(),
        db_path=_get_env("DB_PATH", os.path.join("data", "duckdb", "b3_fundamentals.duckdb")),
        snapshot_dir=_get_env("SNAPSHOT_DIR", os.path.join("data", "snapshots")),
        raw_dir=_get_env("RAW_DIR", os.path.join("data", "raw")),
        brapi_key=_get_env("BRAPI_KEY", ""),
        brapi_base_url=_get_env("BRAPI_BASE_URL", "https://brapi.dev/api"),
        fund_ttl=_get_int("FUND_TTL", 86400),
        log_level=_get_env("LOG_LEVEL", "INFO"),
        queue_dir=_get_env("QUEUE_DIR", "queue"),
        report_min_age_hours=_get_float("REPORT_MIN_AGE_HOURS", 24.0),
        queue_poll_seconds=_get_int("QUEUE_POLL_SECONDS", 60),
        queue_max_trigger_age_hours=_get_float("QUEUE_MAX_TRIGGER_AGE_HOURS", 24.0),
        queue_request_interval_seconds=_get_positive_int("QUEUE_REQUEST_INTERVAL_SECONDS", 60),
        queue_error_cooldown_seconds=_get_positive_int("QUEUE_ERROR_COOLDOWN_SECONDS", 900),
        corporate_events_file=_get_env("CORPORATE_EVENTS_FILE", "").strip(),
    )
