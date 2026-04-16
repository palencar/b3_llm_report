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


def _should_generate(ticker: str, queue_mtime: float, min_age_hours: float) -> tuple[bool, str]:
    """Return (should_generate, reason) for the given ticker.

    Generates if:
    - report does not exist, OR
    - queue file is newer than report (new request) AND report is old enough
    """
    report_path = os.path.join(REPORTS_DIR, f"{ticker}.md")
    if not os.path.exists(report_path):
        return True, "report absent"

    report_mtime = os.path.getmtime(report_path)
    age_hours = (time.time() - report_mtime) / 3600

    if report_mtime >= queue_mtime:
        return False, f"report newer than queue trigger (age: {age_hours:.1f}h)"

    if age_hours < min_age_hours:
        return False, f"report too recent (age: {age_hours:.1f}h < {min_age_hours:.1f}h)"

    return True, f"queue trigger newer than report (age: {age_hours:.1f}h)"


def _process_queue(config) -> None:
    """Process all files currently in config.queue_dir."""
    try:
        entries = os.listdir(config.queue_dir)
    except OSError:
        return

    for name in entries:
        ticker = name.upper()
        if not _TICKER_RE.match(ticker):
            _logger.warning("invalid ticker in queue, skipping: %s", name)
            continue

        filepath = os.path.join(config.queue_dir, name)
        queue_mtime = os.path.getmtime(filepath)
        generate, reason = _should_generate(ticker, queue_mtime, config.report_min_age_hours)

        if not generate:
            _logger.info("skipped %s (%s)", ticker, reason)
            continue

        _logger.info("generating report for %s (%s)", ticker, reason)
        try:
            run_report(ticker)
            _logger.info("generated %s", ticker)
        except Exception:
            _logger.exception("error processing ticker %s", ticker)


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
