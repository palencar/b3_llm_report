"""Snapshot normalizado e reproduzivel para classificacao direta."""

from datetime import date, datetime, timezone
import hashlib
import json
import logging
import math
from pathlib import Path
import re
from decimal import Decimal, InvalidOperation

from b3_report.events import load_event_context, validate_event_context

_logger = logging.getLogger(__name__)
SNAPSHOT_VERSION = "decision-snapshot-v1"
NORMALIZATION_POLICY = "yfinance-primary-fundamentus-valuation-v2"


def _fundamentus_number(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    if re.fullmatch(r"[+-]?(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?", value) is None:
        return None
    try:
        number = Decimal(value.replace(".", "").replace(",", "."))
        parsed = float(number)
        return parsed if math.isfinite(parsed) else None
    except (InvalidOperation, OverflowError):
        return None


def _fundamentus_valuation(payload):
    indicators = payload.get("indicators", {})
    values = {}
    for label, field in (("P/L", "Trailing PE"), ("P/VP", "Price to Book")):
        value = _fundamentus_number(indicators.get(label))
        if value is not None:
            values[field] = value
    if not values:
        return None
    try:
        as_of = datetime.strptime(indicators.get("Data últ cot", ""), "%d/%m/%Y").date().isoformat()
    except (TypeError, ValueError):
        as_of = None
    fetched_at = payload.get("fetched_at")
    try:
        # O cache registra horario local; preservar sua data, sem inventar UTC.
        available = datetime.fromisoformat(fetched_at).date().isoformat() if isinstance(fetched_at, str) and "T" in fetched_at else None
    except ValueError:
        available = None
    return {"value": values, "source": "fundamentus", "as_of": as_of,
            "available_at": available, "conflict": False}


def _timestamp_date(value) -> str | None:
    if type(value) not in (int, float):
        return None
    try:
        return datetime.fromtimestamp(value, timezone.utc).date().isoformat()
    except (ValueError, OverflowError, OSError):
        return None


def _observed_date(value) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    return timestamp.date().isoformat() if timestamp.tzinfo is not None else None


def _values(data: dict, section: str, fields: tuple[str, ...]) -> dict:
    item = data.get(section, {})
    return {field: item[field] for field in fields if item.get(field) is not None}


def build_snapshot(*, ticker: str, analysis_date: str, yfinance_data: dict,
                            fundamentus_text: str, cvm_rows: list,
                            fundamentus_payload: dict | None = None) -> dict:
    """Aplica politica unica de fontes e preserva os dados originais no contexto."""
    metadata = yfinance_data.get("Source Metadata", {})
    price_date = _timestamp_date(metadata.get("Price Time"))
    period_date = _timestamp_date(metadata.get("Financial Period"))
    available = _observed_date(metadata.get("Fetched At"))
    prices = yfinance_data.get("Stock Price", {})
    trading = yfinance_data.get("Trading Information", {})
    evidence = {}

    def add(key, value, as_of):
        evidence[key] = {"value": value, "source": "yfinance", "as_of": as_of,
                         "available_at": available, "conflict": False}

    add("price", prices.get("Current Price"), price_date)
    add("price_trend", _values(yfinance_data, "Stock Price", ("50 Day Average", "200 Day Average", "52 Week Low", "52 Week High")), price_date)
    price, volume = prices.get("Current Price"), trading.get("Average Volume")
    liquidity = price * volume if type(price) in (int, float) and type(volume) in (int, float) else None
    add("liquidity", liquidity, price_date)
    add("valuation", _values(yfinance_data, "Financial Metrics", ("Trailing PE", "Forward PE", "Price to Book")), price_date)
    add("profitability", _values(yfinance_data, "Profitability Ratios", ("Gross Margins", "Profit Margins", "Operating Margins")), period_date)
    add("financial_health", _values(yfinance_data, "Financial Health", ("Total Cash", "Total Debt", "Free Cash Flow", "Operating Cash Flow")), period_date)
    add("growth", _values(yfinance_data, "Financial Metrics", ("Earnings Growth", "Revenue Growth")), period_date)
    serialized_rows = [
        {"period": r[0].isoformat() if hasattr(r[0], "isoformat") else str(r[0]),
         "report_type": r[1], "account_code": r[2], "account_name": r[3], "value": r[4]}
        for r in cvm_rows
    ]
    snapshot = {
        "snapshot_version": SNAPSHOT_VERSION, "ticker": ticker, "analysis_date": analysis_date,
        "normalization_policy": "yfinance-primary-v1",
        "availability_policy": "available_at e a primeira observacao deste snapshot, nao a data original de publicacao",
        "conflict_scope": "grupos primarios de uma fonte; divergencias com contexto complementar nao conciliadas",
        "source_data": {"yfinance": yfinance_data, "fundamentus": fundamentus_text, "cvm": serialized_rows},
        "evidence": evidence, "risk_evidence": {},
    }
    if fundamentus_payload is not None:
        snapshot["source_data"]["fundamentus"] = fundamentus_payload
        snapshot["normalization_policy"] = NORMALIZATION_POLICY
        if not evidence["valuation"]["value"]:
            secondary = _fundamentus_valuation(fundamentus_payload)
            if secondary is not None:
                evidence["valuation"] = secondary
                _logger.info("Normalizacao ticker=%s grupo=valuation fonte=fundamentus politica=%s", ticker, NORMALIZATION_POLICY)
    validate_snapshot(snapshot)
    return snapshot


def validate_snapshot(snapshot: dict) -> None:
    if not isinstance(snapshot, dict) or snapshot.get("snapshot_version") != SNAPSHOT_VERSION:
        raise ValueError("Snapshot de decisao invalido ou de versao desconhecida.")
    ticker = snapshot.get("ticker")
    if not isinstance(ticker, str) or re.fullmatch(r"[A-Z0-9]{3,6}", ticker) is None:
        raise ValueError("Ticker invalido no snapshot.")
    reference = snapshot.get("analysis_date")
    try:
        if not isinstance(reference, str) or date.fromisoformat(reference).isoformat() != reference:
            raise ValueError
    except ValueError as exc:
        raise ValueError("Data de referencia invalida no snapshot.") from exc
    if not isinstance(snapshot.get("evidence"), dict) or not isinstance(snapshot.get("source_data"), dict):
        raise ValueError("Snapshot deve preservar fontes e evidencias estruturadas.")
    if not isinstance(snapshot.get("risk_evidence"), dict):
        raise ValueError("Snapshot deve conter risk_evidence, mesmo quando vazio.")
    allowed = {"snapshot_version", "ticker", "analysis_date", "evidence", "risk_evidence",
               "source_data", "normalization_policy", "availability_policy", "conflict_scope", "event_context"}
    if set(snapshot) - allowed:
        raise ValueError("Snapshot possui campos nao suportados; nao incluir relatorios ou recomendacoes geradas.")
    if "event_context" in snapshot:
        validate_event_context(snapshot["event_context"], ticker, reference)
    if set(snapshot["source_data"]) != {"yfinance", "fundamentus", "cvm"}:
        raise ValueError("source_data deve conter somente as tres fontes de dados.")
    fundamentus = snapshot["source_data"]["fundamentus"]
    if not isinstance(fundamentus, str):
        if (not isinstance(fundamentus, dict)
                or set(fundamentus) != {"text", "indicators", "fetched_at"}
                or not isinstance(fundamentus["text"], str)
                or not isinstance(fundamentus["indicators"], dict)
                or any(not isinstance(k, str) or not isinstance(v, (str, type(None)))
                       for k, v in fundamentus["indicators"].items())
                or not isinstance(fundamentus["fetched_at"], (str, type(None)))):
            raise ValueError("Payload estruturado do Fundamentus invalido.")
    for horizon, directions in snapshot["risk_evidence"].items():
        if horizon not in ("curtissimo", "curto", "medio") or not isinstance(directions, dict):
            raise ValueError("Horizonte invalido nas evidencias de risco.")
        for direction, groups in directions.items():
            if direction not in ("comprada", "vendida") or not isinstance(groups, dict):
                raise ValueError("Direcao ou grupos invalidos nas evidencias de risco.")
            if set(groups) - {"adverse_scenario", "borrow_availability", "borrow_cost", "borrow_terms"}:
                raise ValueError("Evidencias de risco nao podem substituir os grupos primarios.")
    try:
        json.dumps(snapshot, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("Snapshot contem valores que nao podem ser representados como JSON valido.") from exc


def snapshot_id(snapshot: dict) -> str:
    validate_snapshot(snapshot)
    content = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def load_snapshot(path: str | Path) -> dict:
    """Le snapshot avulso ou extrai o snapshot do estado atual autocontido."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and data.get("version") in ("assessment-state-v1", "assessment-state-v2"):
        snapshot = data.get("snapshot")
        validate_snapshot(snapshot)
        if data.get("dataset_id") != snapshot_id(snapshot) or data.get("ticker") != snapshot["ticker"]:
            raise ValueError("Snapshot combinado diverge do controle.")
        return snapshot
    validate_snapshot(data)
    return data






def collect_snapshot(symbol: str, config, analysis_date: str) -> dict:
    # Importacoes locais permitem testar replay sem carregar os coletores.
    from b3_report.sources.yfinance import extract_yfinance_info
    from b3_report.sources.fundamentus import get_complementary_payload
    from b3_report.sources.cvm import fetch_raw_rows

    yfinance_data = json.loads(extract_yfinance_info(f"{symbol}.SA"))
    fundamentus = get_complementary_payload(symbol, db_path=config.db_path, ttl_seconds=config.fund_ttl)
    rows = fetch_raw_rows(symbol, config.db_path)
    if not rows:
        _logger.warning("Snapshot ticker=%s sem demonstrativos CVM; ausencia preservada.", symbol)
    snapshot = build_snapshot(ticker=symbol, analysis_date=analysis_date,
                                   yfinance_data=yfinance_data, fundamentus_text=fundamentus["text"],
                                   cvm_rows=rows or [], fundamentus_payload=fundamentus)
    context = load_event_context(config, symbol, yfinance_data=yfinance_data)
    if context is not None:
        snapshot["event_context"] = context
        validate_snapshot(snapshot)
    return snapshot
