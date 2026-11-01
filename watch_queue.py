"""Watch queue: monitora queue_dir e gera relatórios LLM por ticker."""
import logging
import argparse
import json
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
from b3_report.llm import validate_llm_config
from b3_report.aligned_pipeline import aligned_job_path, run_aligned, should_run_aligned
from b3_report.textual_baseline import format_report_markdown
from b3_report.events import active_event, event_token, load_event_context

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


def _calendar_changed(config, ticker, context):
    if context is None:
        return False
    path = aligned_job_path(config, ticker)
    if not path.exists():
        return False
    state = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(state, dict):
        raise ValueError(f"Estado do relatorio invalido: {path}")
    return event_token(context) != state.get("event_state")


def _process_queue(config, *, structured_output=False) -> None:
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
            _logger.warning("Ticker invalido na fila; item ignorado: %s", name)
            continue

        queue_mtime = os.path.getmtime(filepath)
        structured = {"structured_output": True} if structured_output else {}
        try:
            # Um evento ativo pode reavaliar ticker ja presente, sem criar alertas.
            context = load_event_context(config, ticker)
            event_refresh = active_event(context) or _calendar_changed(config, ticker, context)
            if not event_refresh and _is_stale_queue_trigger(filepath, queue_mtime, config.queue_max_trigger_age_hours):
                continue
            generate, reason = should_run_aligned(config, ticker, queue_mtime, **structured)
        except (ValueError, FileNotFoundError) as exc:
            _logger.error("Estado do relatorio invalido ticker=%s; item preservado e demais itens "
                          "seguem. Detalhe: %s", ticker, exc)
            _SKIPPED_TRIGGERS[filepath] = (queue_mtime, "controle invalido")
            continue
        if not generate:
            _log_skip_once(filepath, ticker, queue_mtime, reason)
            continue
        _LAST_ATTEMPTED_ENTRY = name
        failed = False
        try:
            outcome = run_aligned(ticker, config=config,
                                  trigger_mtime=queue_mtime, reports_dir=REPORTS_DIR, **structured)
            if "unified" in outcome["results"]:
                print(format_report_markdown(outcome["results"]["unified"]), flush=True)
            failed = bool(outcome["failed_modes"])
        except Exception:
            failed = True
            _logger.exception("Falha no relatorio unificado ticker=%s; controle preservado.", ticker)
        delay = config.queue_request_interval_seconds
        if failed:
            delay = max(delay, config.queue_error_cooldown_seconds)
            _logger.error("Erro ao processar ticker=%s; fila pausada por %ds. Item preservado.", ticker, delay)
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


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Monitorar fila de relatorios.")
    parser.add_argument("--unified", action="store_true", help="Alias de compatibilidade; o unificado e o unico fluxo.")
    parser.add_argument("--structured-output", choices=("on", "off"), default="off",
                        help="Solicita JSON Schema na API de chat; padrao off, sem fallback automatico.")
    args = parser.parse_args(argv)
    load_dotenv()
    config = load_config()
    validate_llm_config(config.llm_model, config.openai_url_base, config.ollama_url_base)
    os.makedirs(config.queue_dir, exist_ok=True)
    os.makedirs(REPORTS_DIR, exist_ok=True)
    _logger.info("watch_queue started: queue_dir=%s poll=%ds min_age=%.1fh max_trigger_age=%.1fh",
                 config.queue_dir, config.queue_poll_seconds, config.report_min_age_hours,
                 config.queue_max_trigger_age_hours)
    _logger.info("Relatorio unificado: modelo=%s; classificacoes experimentais, sem aprovacao financeira.",
                 config.llm_model)
    _logger.info("Structured output: %s; sem fallback automatico.", args.structured_output)
    while True:
        structured = {"structured_output": True} if args.structured_output == "on" else {}
        _process_queue(config, **structured)
        time.sleep(config.queue_poll_seconds)


if __name__ == "__main__":
    main()
