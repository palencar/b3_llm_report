import os
from datetime import datetime

from dotenv import load_dotenv

from b3_core.config import load_config
from b3_report.llm import get_investment_analysis
from b3_report.prompts import prepare_llm_investment_analysis_request
from b3_report.sources.fundamentus import get_complementary_data
from b3_report.sources.yfinance import get_yfinance_data


def run_report(symbol: str) -> str:
    load_dotenv()
    config = load_config()
    normalized_symbol = symbol.upper()
    analysis_date = datetime.now().strftime("%Y-%m-%d")

    yfinance_report = get_yfinance_data(f"{normalized_symbol}.SA")
    complementary_report = get_complementary_data(normalized_symbol)
    llm_prompt = prepare_llm_investment_analysis_request(
        yfinance_report,
        complementary_report,
        analysis_date,
    )
    analysis = get_investment_analysis(
        llm_prompt,
        api_key=config.openai_api_key,
        base_url=config.openai_url_base,
        model=config.openai_model_name,
    )

    os.makedirs("reports", exist_ok=True)
    report_path = os.path.join("reports", f"{normalized_symbol}.md")
    with open(report_path, "w", encoding="utf-8") as file:
        file.write(analysis)
    return analysis
