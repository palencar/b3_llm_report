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
