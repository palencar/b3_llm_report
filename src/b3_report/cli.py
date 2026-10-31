import logging
import os
from datetime import datetime

from dotenv import load_dotenv

from b3_core.config import load_config
from b3_report.llm import get_investment_analysis, validate_llm_config, LLMError
from b3_report.prompts import prepare_llm_investment_analysis_request
from b3_report.sources.cvm import get_cvm_data
from b3_report.sources.fundamentus import get_complementary_data
from b3_report.sources.yfinance import get_yfinance_data


_logger = logging.getLogger(__name__)

_KNOWN_ERROR_PREFIXES = (
    "Erro ao fazer chamada ao Ollama:",
    "Error calling Ollama:",
)

class ReportValidationError(RuntimeError):
    """Resposta do LLM fora do contrato esperado para persistencia."""


def run_report(symbol: str) -> str:
    load_dotenv()
    config = load_config()
    validate_llm_config(config.llm_model, config.openai_url_base, config.ollama_url_base)
    normalized_symbol = symbol.upper()
    analysis_date = datetime.now().strftime("%Y-%m-%d")

    yfinance_report = get_yfinance_data(f"{normalized_symbol}.SA")
    complementary_report = get_complementary_data(normalized_symbol)
    cvm_report = get_cvm_data(normalized_symbol, config.db_path)
    llm_prompt = prepare_llm_investment_analysis_request(
        yfinance_report,
        complementary_report,
        analysis_date,
        cvm_info=cvm_report,
    )
    try:
        analysis = get_investment_analysis(
            llm_prompt,
            api_key=config.llm_api_key,
            openai_url_base=config.openai_url_base,
            ollama_url_base=config.ollama_url_base,
            model=config.llm_model,
        )
        _validate_report_content(analysis, normalized_symbol, analysis_date)
    except (LLMError, ReportValidationError):
        _logger.error(
            "Falha ao gerar relatorio valido para ticker=%s; persistencia cancelada.",
            normalized_symbol,
        )
        raise

    os.makedirs("reports", exist_ok=True)
    report_path = os.path.join("reports", f"{normalized_symbol}.md")
    with open(report_path, "w", encoding="utf-8") as file:
        file.write(analysis)
    return analysis


def _validate_report_content(analysis: str, ticker: str, analysis_date: str) -> None:
    stripped = analysis.strip()
    if not stripped:
        raise ReportValidationError(
            f"Resposta vazia do LLM para ticker={ticker}."
        )
    if stripped.startswith(_KNOWN_ERROR_PREFIXES):
        raise ReportValidationError(
            f"Resposta de erro do LLM recebida como texto para ticker={ticker}."
        )

    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    first_lines = lines[:5]
    has_company = any(
        line.startswith("- Empresa:") and line.split(":", 1)[1].strip()
        for line in first_lines
    )
    has_analysis_date = f"- Data da Análise: {analysis_date}" in first_lines
    if (
        not lines
        or lines[0] != "#### Identificação"
        or not has_company
        or not has_analysis_date
    ):
        raise ReportValidationError(
            f"Resposta do LLM fora do formato esperado para ticker={ticker}; "
            "identificacao inicial ausente ou incompleta."
        )

    required_markers = (
        "Identificação",
        "Resumo",
        "Curtíssimo Prazo",
        "Curto Prazo",
        "Médio Prazo",
    )
    missing_markers = [marker for marker in required_markers if marker not in stripped]
    if missing_markers:
        raise ReportValidationError(
            f"Resposta do LLM fora do formato esperado para ticker={ticker}; ausentes: {', '.join(missing_markers)}."
        )
