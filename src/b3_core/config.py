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
    )
