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
from b3_report.llm import validate_llm_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
_logger = logging.getLogger(__name__)

REPORTS_DIR = "reports"
_TICKER_RE = re.compile(r"^[A-Z0-9]{3,6}$")
_IGNORED_STALE_TRIGGERS: dict[str, float] = {}
_SKIPPED_TRIGGERS: dict[str, tuple[float, str]] = {}
_NEXT_ATTEMPT_AT = 0.0
_LAST_ATTEMPTED_ENTRY: str | None = None


def _resolve_report_path(ticker: str) -> str | None:
    current_report = os.path.join(REPORTS_DIR, f"{ticker}.md")
    if os.path.exists(current_report):
        return current_report

    legacy_report = os.path.join(REPORTS_DIR, ticker)
    if os.path.isfile(legacy_report):
        return legacy_report

    return None


def _should_generate(ticker: str, queue_mtime: float, min_age_hours: float) -> tuple[bool, str]:
    """Return (should_generate, reason) for the given ticker.

    Generates if:
    - report does not exist, OR
    - queue file is newer than report (new request) AND report is old enough
    """
    report_path = _resolve_report_path(ticker)
    if report_path is None:
        return True, "report absent"

    report_mtime = os.path.getmtime(report_path)
    age_hours = (time.time() - report_mtime) / 3600

    if report_mtime >= queue_mtime:
        return False, f"report newer than queue trigger (age: {age_hours:.1f}h)"

    if age_hours < min_age_hours:
        return False, f"report too recent (age: {age_hours:.1f}h < {min_age_hours:.1f}h)"

    return True, f"queue trigger newer than report (age: {age_hours:.1f}h)"


def _process_queue(config) -> None:
    """Processa no maximo uma tentativa por intervalo, preservando a fila."""
    global _NEXT_ATTEMPT_AT, _LAST_ATTEMPTED_ENTRY
    if time.monotonic() < _NEXT_ATTEMPT_AT:
        return
    try:
        entries = sorted(os.listdir(config.queue_dir))
    except OSError:
        return

    # Retoma depois do ultimo item tentado, inclusive quando ele falhou.
    if _LAST_ATTEMPTED_ENTRY is not None:
        entries = (
            [name for name in entries if name > _LAST_ATTEMPTED_ENTRY]
            + [name for name in entries if name <= _LAST_ATTEMPTED_ENTRY]
        )

    for name in entries:
        ticker = name.upper()
        filepath = os.path.join(config.queue_dir, name)
        if not os.path.isfile(filepath):
            continue
        if not _TICKER_RE.match(ticker):
            _logger.warning("Ticker invalido na fila, ignorando: %s", name)
            continue

        queue_mtime = os.path.getmtime(filepath)
        if _is_stale_queue_trigger(filepath, queue_mtime, config.queue_max_trigger_age_hours):
            continue
        generate, reason = _should_generate(ticker, queue_mtime, config.report_min_age_hours)
        if not generate:
            _log_skip_once(filepath, ticker, queue_mtime, reason)
            continue

        _LAST_ATTEMPTED_ENTRY = name
        failed = False
        _logger.info("Processando ticker=%s modo=report modelo=%s (%s)", ticker, config.llm_model, reason)
        try:
            run_report(ticker)
            _logger.info("Concluido ticker=%s modo=report", ticker)
        except Exception:
            failed = True
            _logger.exception("Falha ticker=%s modo=report; item preservado.", ticker)
        delay = config.queue_request_interval_seconds
        if failed:
            delay = max(delay, config.queue_error_cooldown_seconds)
            _logger.error(
                "Erro ao processar ticker=%s; fila pausada por %ds. Item preservado.",
                ticker,
                delay,
            )

        _NEXT_ATTEMPT_AT = time.monotonic() + delay
        _IGNORED_STALE_TRIGGERS.pop(filepath, None)
        _SKIPPED_TRIGGERS.pop(filepath, None)
        return


def _log_skip_once(filepath: str, ticker: str, queue_mtime: float, reason: str) -> None:
    reason_key = reason.split(" (", 1)[0]
    skip_key = (queue_mtime, reason_key)
    if _SKIPPED_TRIGGERS.get(filepath) == skip_key:
        return

    _logger.info("skipped %s (%s)", ticker, reason)
    _SKIPPED_TRIGGERS[filepath] = skip_key


def _is_stale_queue_trigger(filepath: str, queue_mtime: float, max_age_hours: float) -> bool:
    age_hours = (time.time() - queue_mtime) / 3600
    if age_hours <= max_age_hours:
        _IGNORED_STALE_TRIGGERS.pop(filepath, None)
        return False

    previous_mtime = _IGNORED_STALE_TRIGGERS.get(filepath)
    if previous_mtime != queue_mtime:
        _logger.info(
            "ignored stale queue trigger: %s (age: %.1fh > %.1fh)",
            os.path.basename(filepath),
            age_hours,
            max_age_hours,
        )
        _IGNORED_STALE_TRIGGERS[filepath] = queue_mtime
    return True


def main() -> None:
    load_dotenv()
    config = load_config()
    validate_llm_config(config.llm_model, config.openai_url_base, config.ollama_url_base)
    os.makedirs(config.queue_dir, exist_ok=True)
    os.makedirs(REPORTS_DIR, exist_ok=True)
    _logger.info(
        "watch_queue started: queue_dir=%s poll=%ds min_age=%.1fh max_trigger_age=%.1fh",
        config.queue_dir,
        config.queue_poll_seconds,
        config.report_min_age_hours,
        config.queue_max_trigger_age_hours,
    )
    while True:
        _process_queue(config)
        time.sleep(config.queue_poll_seconds)


if __name__ == "__main__":
    main()
