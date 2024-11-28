import yfinance as yf
import json


def extract_yfinance_info(symbol: str):
    """
    Função para obter informações completas de ações usando yfinance.

    Args:
        symbol (str): Símbolo da ação

    Returns:
        str: Informações completas da ação em formato JSON
    """
    stock = yf.Ticker(symbol)
    info = stock.info
    recommendations = stock.recommendations

    return json.dumps({
        "Basic Info": {
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
            "Address": f"{info.get('address1', '')} {info.get('city', '')} {info.get('state', '')} {info.get('zip', '')} {info.get('country', '')}".strip(),
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
        "Analyst Recommendations": recommendations.set_index('period').to_dict(orient="index") if recommendations is not None and len(recommendations) > 0 else {}
    }, indent=2)


def format_yfinace_data(stock_data):
    formatted_text = f"""📊 Relatório Detalhado da Ação {stock_data['Basic Info']['Symbol']}

🏢 Informações Básicas
- Nome: {stock_data['Basic Info']['Name']}
- Setor: {stock_data['Company Details']['Sector']}
- Indústria: {stock_data['Company Details']['Industry']}
- Website: {stock_data['Basic Info'].get('Website', 'N/A')}

💰 Preço e Desempenho
- Preço Atual: {stock_data['Stock Price']['Current Price']} {stock_data['Basic Info']['Currency']}
- Mínima 52 semanas: {stock_data['Stock Price']['52 Week Low']}
- Máxima 52 semanas: {stock_data['Stock Price']['52 Week High']}

📈 Métricas Financeiras
- Capitalização de Mercado: {stock_data['Financial Metrics'].get('Market Cap', 'N/A')}
- P/L (Atual): {stock_data['Financial Metrics'].get('Trailing PE', 'N/A')}
- P/L (Projetado): {stock_data['Financial Metrics'].get('Forward PE', 'N/A')}
- EPS (Atual): {stock_data['Financial Metrics'].get('Trailing EPS', 'N/A')}
- EPS (Projetado): {stock_data['Financial Metrics'].get('Forward EPS', 'N/A')}
- Dividend Yield: {stock_data['Financial Metrics'].get('Dividend Yield', 'N/A')}

📊 Recomendações de Analistas"""

    for period, rec in stock_data['Analyst Recommendations'].items():
        period_text = {
            '0m': 'Período Atual',
            '-1m': '1 Mês Atrás',
            '-2m': '2 Meses Atrás',
            '-3m': '3 Meses Atrás'
        }.get(period, period)

        formatted_text += f"\n- {period_text}: Strong Buy: {rec.get('strongBuy', 0)}, Buy: {rec.get('buy', 0)}, Hold: {rec.get('hold', 0)}, Sell: {rec.get('sell', 0)}, Strong Sell: {rec.get('strongSell', 0)}"

    formatted_text += f"""

🎯 Preços-Alvo dos Analistas
- Mínimo: {stock_data['Analyst Insights'].get('Target Low Price', 'N/A')}
- Médio: {stock_data['Analyst Insights'].get('Target Mean Price', 'N/A')}
- Máximo: {stock_data['Analyst Insights'].get('Target High Price', 'N/A')}

💡 Resumo de Negócios
{stock_data['Basic Info'].get('Business Summary', 'Sem informações disponíveis')}
"""
    return formatted_text


def get_yfinance_data(ticker):
    yfinance_data = extract_yfinance_info(ticker)
    return format_yfinace_data(json.loads(yfinance_data))
