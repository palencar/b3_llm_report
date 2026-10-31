"""Módulo para buscar histórico de relatórios anteriores."""
import logging
import os
import tempfile
from datetime import datetime, timedelta
from typing import Literal
from pathlib import Path
_logger = logging.getLogger(__name__)
_HISTORY_ROOT = "_history"


def get_recent_reports_history(
    ticker: str,
    report_dir: str = "reports",
    n: int | Literal["last_month"] = 4,
) -> str:
    """
    Ler os últimos n relatórios do ticker e retornar o texto concatenado.

    Args:
        ticker: Símbolo da ação (ex: "PETR4")
        report_dir: Diretório com relatórios (default: "reports")
        n: Número de relatórios (default 4) ou `"last_month"` para filtrar por últimos 30 dias

    Returns:
        Texto com os últimos n relatórios, ordenados por data (desc)
    """
    report_files = []
    for history_dir in _iter_history_dirs(Path(report_dir), ticker):
        for file_path in history_dir.glob("*.md"):
            report_timestamp = _parse_report_timestamp(file_path)
            if report_timestamp is None:
                _logger.warning(
                    "Arquivo de historico ignorado por nome fora do contrato: %s",
                    file_path.name,
                )
                continue
            report_files.append((report_timestamp, file_path))

    if not report_files:
        legacy_report = _get_legacy_report_file(Path(report_dir), ticker)
        if legacy_report is None:
            return ""
        report_files.append((datetime.fromtimestamp(legacy_report.stat().st_mtime), legacy_report))

    report_files.sort(key=lambda item: item[0], reverse=True)

    # last_month mode: filter by date window
    if isinstance(n, str):
        cutoff = datetime.now() - timedelta(days=_WINDOW_DAYS)
        report_files = [f for f in report_files if f[0] >= cutoff]
    # All files within window when n is "last_month"; otherwise cap by count
    end = None if isinstance(n, str) else n
    history_parts = []
    for report_timestamp, file_path in report_files[:end]:
        content = file_path.read_text(encoding="utf-8")
        date_str = report_timestamp.strftime("%Y-%m-%d %H:%M:%S")
        history_parts.append(f"- **{date_str}** - {file_path.name}\n{content}")

    return "\n".join(history_parts)


_WINDOW_DAYS = 30


def save_report_snapshot(
    ticker: str,
    content: str,
    analysis_timestamp: datetime,
    report_dir: str = "reports",
) -> Path:
    history_dir = _get_snapshot_dir(Path(report_dir), ticker)
    history_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = history_dir / f"{analysis_timestamp.strftime('%Y-%m-%d_%H%M%S')}.md"
    write_report_file_atomic(snapshot_path, content)
    return snapshot_path


def write_report_file_atomic(target_path: Path | str, content: str) -> Path:
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_file.write(content)
            temp_file.flush()
            os.fsync(temp_file.fileno())
            temp_path = Path(temp_file.name)
        os.replace(temp_path, target)
        temp_path = None
        return target
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def _iter_history_dirs(report_root: Path, ticker: str) -> list[Path]:
    history_dirs = []

    legacy_dir = report_root / ticker
    if legacy_dir.is_dir():
        history_dirs.append(legacy_dir)

    alternative_dir = report_root / _HISTORY_ROOT / ticker
    if alternative_dir.is_dir():
        history_dirs.append(alternative_dir)

    return history_dirs


def _get_snapshot_dir(report_root: Path, ticker: str) -> Path:
    legacy_dir = report_root / ticker
    if legacy_dir.is_dir():
        return legacy_dir

    alternative_dir = report_root / _HISTORY_ROOT / ticker
    if legacy_dir.exists():
        _logger.warning(
            "Caminho legado de historico conflita com arquivo existente: %s. Usando %s.",
            legacy_dir,
            alternative_dir,
        )
    return alternative_dir


def _get_legacy_report_file(report_root: Path, ticker: str) -> Path | None:
    current_report = report_root / f"{ticker}.md"
    if current_report.is_file():
        return current_report

    legacy_report = report_root / ticker
    if legacy_report.is_file():
        _logger.warning(
            "Arquivo de relatorio legado sem extensao usado como historico: %s",
            legacy_report,
        )
        return legacy_report
    return None


def _parse_report_timestamp(file_path: Path) -> datetime | None:
    try:
        return datetime.strptime(file_path.stem, "%Y-%m-%d_%H%M%S")
    except ValueError:
        return None
