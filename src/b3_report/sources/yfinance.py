import json
from datetime import datetime, timezone

import yfinance as yf

EVENT_SOURCE_VERSION = "yahoo-info-earnings-v1"
_EVENT_FIELDS = ("earningsTimestamp", "earningsTimestampStart", "earningsTimestampEnd",
                 "earningsCallTimestamp", "isEarningsDateEstimate", "exchangeTimezoneName")


def _event_metadata(info: dict) -> dict:
    """Preserva somente campos ja retornados por info, sem nova consulta."""
    raw = {key: info[key] for key in _EVENT_FIELDS if key in info}
    dates = {}
    for key in _EVENT_FIELDS[:4]:
        value = raw.get(key)
        if type(value) not in (int, float):
            continue
        try:
            dates[key] = datetime.fromtimestamp(value, timezone.utc).isoformat()
        except (ValueError, OverflowError, OSError):
            continue
    estimate = raw.get("isEarningsDateEstimate")
    certainty = "estimativa" if estimate is True else "nao_marcada_como_estimativa" if estimate is False else "desconhecida"
    return {
        "version": EVENT_SOURCE_VERSION, "source": "Yahoo Finance via yfinance.Ticker.info",
        "status": "datas_reportadas" if dates else "datas_nao_fornecidas_em_info",
        "raw_fields": raw, "timestamps_utc": dates, "certainty": certainty,
        "availability": "observado em Source Metadata.Fetched At; publicacao original desconhecida",
        "limitations": "Pode ser intervalo ou estimativa. Horario do fornecedor nao e horario confirmado pelo RI. "
                       "Data passada nao confirma divulgacao nem incorporacao aos dados. Ausencia nao comprova ausencia de evento.",
    }


def format_event_metadata(metadata: dict) -> str:
    lines = ["Eventos de Resultados (Yahoo Finance, nao confirmados pelo RI)",
             f"- Disponibilidade: {metadata['status']}; certeza: {metadata['certainty']}"]
    for field, timestamp in metadata["timestamps_utc"].items():
        lines.append(f"- {field}: {timestamp}")
    if metadata["raw_fields"].get("exchangeTimezoneName"):
        lines.append(f"- Fuso reportado pela bolsa: {metadata['raw_fields']['exchangeTimezoneName']}")
    lines.append("- Limitacoes: " + metadata["limitations"])
    return "\n".join(lines)


def extract_yfinance_info(symbol: str) -> str:
    stock = yf.Ticker(symbol)
    info = stock.info
    recommendations = stock.recommendations

    return json.dumps(
        {
            "Source Metadata": {
                "Fetched At": datetime.now(timezone.utc).isoformat(),
                "Price Time": info.get("regularMarketTime"),
                "Financial Period": info.get("mostRecentQuarter"),
            },
            "Event Metadata": _event_metadata(info),
            "Basic Info": {
                "Quote Type": info.get("quoteType"),
                "Name": info.get("shortName"),
                "Symbol": info.get("symbol"),
                "Currency": info.get("currency", "USD"),
                "Website": info.get("website"),
                "Business Summary": info.get("longBusinessSummary"),
            },
            "Stock Price": {
                "Current Price": info.get("regularMarketPrice", info.get("currentPrice")),
                "52 Week Low": info.get("fiftyTwoWeekLow"),
                "52 Week High": info.get("fiftyTwoWeekHigh"),
                "50 Day Average": info.get("fiftyDayAverage"),
                "200 Day Average": info.get("twoHundredDayAverage"),
            },
            "Company Details": {
                "Sector": info.get("sector"),
                "Industry": info.get("industry"),
                "Employees": info.get("fullTimeEmployees"),
                "Address": (
                    f"{info.get('address1', '')} {info.get('city', '')} "
                    f"{info.get('state', '')} {info.get('zip', '')} {info.get('country', '')}"
                ).strip(),
            },
            "Financial Metrics": {
                "Market Cap": info.get("marketCap"),
                "Enterprise Value": info.get("enterpriseValue"),
                "Trailing PE": info.get("trailingPE"),
                "Forward PE": info.get("forwardPE"),
                "Price to Book": info.get("priceToBook"),
                "Dividend Yield": info.get("dividendYield"),
                "Trailing EPS": info.get("trailingEps"),
                "Forward EPS": info.get("forwardEps"),
                "Earnings Growth": info.get("earningsGrowth"),
                "Revenue Growth": info.get("revenueGrowth"),
            },
            "Profitability Ratios": {
                "Gross Margins": info.get("grossMargins"),
                "EBITDA Margins": info.get("ebitdaMargins"),
                "Profit Margins": info.get("profitMargins"),
                "Operating Margins": info.get("operatingMargins"),
            },
            "Financial Health": {
                "Total Cash": info.get("totalCash"),
                "Total Debt": info.get("totalDebt"),
                "Free Cash Flow": info.get("freeCashflow"),
                "Operating Cash Flow": info.get("operatingCashflow"),
                "EBITDA": info.get("ebitda"),
            },
            "Analyst Insights": {
                "Recommendation": info.get("recommendationKey"),
                "Number of Analyst Opinions": info.get("numberOfAnalystOpinions"),
                "Target Low Price": info.get("targetLowPrice"),
                "Target Mean Price": info.get("targetMeanPrice"),
                "Target High Price": info.get("targetHighPrice"),
            },
            "Trading Information": {
                "Beta": info.get("beta"),
                "Volume": info.get("volume"),
                "Average Volume": info.get("averageVolume"),
            },
            "Analyst Recommendations": (
                recommendations.set_index("period").to_dict(orient="index")
                if recommendations is not None and len(recommendations) > 0
                else {}
            ),
        },
        indent=2,
    )


def format_yfinance_data(stock_data: dict) -> str:
    formatted_text = f"""Relatório Detalhado da Ação {stock_data['Basic Info']['Symbol']}

Informações Básicas
- Nome: {stock_data['Basic Info']['Name']}
- Setor: {stock_data['Company Details']['Sector']}
- Indústria: {stock_data['Company Details']['Industry']}
- Website: {stock_data['Basic Info'].get('Website', 'N/A')}

Preço e Desempenho
- Preço Atual: {stock_data['Stock Price']['Current Price']} {stock_data['Basic Info']['Currency']}
- Mínima 52 semanas: {stock_data['Stock Price']['52 Week Low']}
- Máxima 52 semanas: {stock_data['Stock Price']['52 Week High']}

Métricas Financeiras
- Capitalização de Mercado: {stock_data['Financial Metrics'].get('Market Cap', 'N/A')}
- P/L (Atual): {stock_data['Financial Metrics'].get('Trailing PE', 'N/A')}
- P/L (Projetado): {stock_data['Financial Metrics'].get('Forward PE', 'N/A')}
- EPS (Atual): {stock_data['Financial Metrics'].get('Trailing EPS', 'N/A')}
- EPS (Projetado): {stock_data['Financial Metrics'].get('Forward EPS', 'N/A')}
- Dividend Yield: {stock_data['Financial Metrics'].get('Dividend Yield', 'N/A')}

Recomendações de Analistas"""

    for period, rec in stock_data["Analyst Recommendations"].items():
        period_text = {
            "0m": "Período Atual",
            "-1m": "1 Mês Atrás",
            "-2m": "2 Meses Atrás",
            "-3m": "3 Meses Atrás",
        }.get(period, period)
        formatted_text += (
            f"\n- {period_text}: Strong Buy: {rec.get('strongBuy', 0)}, "
            f"Buy: {rec.get('buy', 0)}, Hold: {rec.get('hold', 0)}, "
            f"Sell: {rec.get('sell', 0)}, Strong Sell: {rec.get('strongSell', 0)}"
        )

    formatted_text += f"""

Preços-Alvo dos Analistas
- Mínimo: {stock_data['Analyst Insights'].get('Target Low Price', 'N/A')}
- Médio: {stock_data['Analyst Insights'].get('Target Mean Price', 'N/A')}
- Máximo: {stock_data['Analyst Insights'].get('Target High Price', 'N/A')}

Resumo de Negócios
{stock_data['Basic Info'].get('Business Summary', 'Sem informações disponíveis')}
"""
    if "Event Metadata" in stock_data:
        formatted_text += "\n\n" + format_event_metadata(stock_data["Event Metadata"])
    return formatted_text


def get_yfinance_data(ticker: str, *, on_data=None) -> str:
    yfinance_data = extract_yfinance_info(ticker)
    data = json.loads(yfinance_data)
    if on_data is not None:
        on_data(data)
    return format_yfinance_data(data)
