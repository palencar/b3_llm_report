"""Source CVM: busca demonstrativos oficiais do DuckDB para o relatório LLM."""
import logging
import os
from collections import defaultdict

from b3_storage.db import connect

_logger = logging.getLogger(__name__)


_TYPE_LABELS = {
    "BPA": "Balanço Patrimonial Ativo (BPA)",
    "BPP": "Balanço Patrimonial Passivo (BPP)",
    "DRE": "Demonstração do Resultado (DRE)",
    "DFC_MI": "Fluxo de Caixa (DFC)",
    "DFC_MD": "Fluxo de Caixa (DFC)",
}

_QUERY = """
    SELECT s.period, s.report_type, s.account_code, s.account_name, s.value
    FROM cvm_statements s
    JOIN cvm_companies c ON c.cnpj = s.cnpj
    -- ticker_map.cnpj é dígitos apenas (normalizado por parse_b3_results no ingest)
    JOIN ticker_map t    ON regexp_replace(c.cnpj, '[^0-9]', '', 'g') = t.cnpj
    WHERE t.ticker = ?
      AND s.report_type IN ('BPA', 'BPP', 'DRE', 'DFC_MI', 'DFC_MD')
      AND LENGTH(s.account_code) - LENGTH(REPLACE(s.account_code, '.', '')) <= 1
    ORDER BY s.report_type, s.account_code, s.period
"""


def _extract_year(period) -> int:
    return period.year if hasattr(period, "year") else int(str(period)[:4])


def _format_value(value: float) -> str:
    if value is None:
        return "N/D"
    abs_val = abs(int(value))
    formatted = f"{abs_val:,}".replace(",", ".")
    return f"-R${formatted}" if value < 0 else f"R${formatted}"


def _build_text(ticker: str, rows: list) -> str:
    grouped: dict = defaultdict(lambda: defaultdict(dict))
    names: dict = {}
    for period, report_type, account_code, account_name, value in rows:
        year = _extract_year(period)
        label = _TYPE_LABELS.get(report_type, report_type)
        grouped[label][account_code][year] = value
        names[account_code] = account_name

    lines = [f"Demonstrativos CVM Oficiais — {ticker}", ""]
    for type_label, accounts in grouped.items():
        lines.append(type_label)
        for code, year_values in sorted(accounts.items()):
            parts = " | ".join(
                f"{yr}={_format_value(val)}" for yr, val in sorted(year_values.items())
            )
            lines.append(f"- {names.get(code, code)} ({code}): {parts}")
        lines.append("")
    return "\n".join(lines).strip()


def _normalize_ticker(ticker: str) -> str:
    """Strip trailing digit from B3 ticker (e.g. 'PETR4' → 'PETR', 'VALE3' → 'VALE').

    The B3 listing API returns base codes without the share-class suffix.
    """
    if ticker and ticker[-1].isdigit():
        return ticker[:-1]
    return ticker


def get_cvm_data(ticker: str, db_path: str) -> str:
    """Return formatted CVM statements for ticker, or '' if unavailable."""
    if not os.path.exists(db_path):
        return ""
    try:
        con = connect(db_path, read_only=True)
    except Exception as e:
        _logger.warning("CVM connect error for db_path=%s: %s", db_path, e)
        return ""
    lookup_ticker = _normalize_ticker(ticker)
    try:
        row = con.execute(
            "SELECT 1 FROM ticker_map WHERE ticker = ? LIMIT 1", [lookup_ticker]
        ).fetchone()
        if row is None:
            return ""
        rows = con.execute(_QUERY, [lookup_ticker]).fetchall()
        if not rows:
            return ""
        max_year = max(_extract_year(r[0]) for r in rows)
        rows = [r for r in rows if _extract_year(r[0]) >= max_year - 2]
        return _build_text(ticker, rows)
    except Exception as e:
        _logger.warning("CVM query error for ticker=%s: %s", ticker, e)
        return ""
    finally:
        con.close()
