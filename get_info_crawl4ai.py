import os
import asyncio
import json
from crawl4ai import AsyncWebCrawler
from crawl4ai.extraction_strategy import LLMExtractionStrategy
from pydantic import BaseModel, Field
from typing import Optional


class StockInfo(BaseModel):
    papel: str = Field(..., description="Código da ação")
    cotacao: str = Field(..., description="Cotação atual da ação")
    tipo: str = Field(..., description="Tipo de ação")
    data_ultima_cotacao: str = Field(..., description="Data da última cotação")
    empresa: str = Field(..., description="Nome da empresa")
    setor: str = Field(..., description="Setor da empresa")
    subsetor: str = Field(..., description="Subsetor da empresa")

    valor_mercado: str = Field(..., description="Valor de mercado")
    valor_firma: str = Field(..., description="Valor da firma")
    numero_acoes: str = Field(..., description="Número de ações")

    oscilacoes: Optional[dict] = Field(None, description="Oscilações da ação")

    indicadores_fundamentalistas: Optional[dict] = Field(None, description="Indicadores fundamentalistas")

    balanco_patrimonial: Optional[dict] = Field(None, description="Dados do Balanço Patrimonial")

    demonstrativos_resultados: Optional[dict] = Field(None, description="Demonstrativos de Resultados")


async def extract_stock_info(url: str):
    async with AsyncWebCrawler(verbose=True) as crawler:
        result = await crawler.arun(
            url=url,
            word_count_threshold=1,
            extraction_strategy=LLMExtractionStrategy(
                provider=os.getenv('CRAWL4AI_MODEL_PROVIDER'), # 'ollama/llama3.1:8b-8k'
                url_base=os.getenv('CRAWL4AI_MODEL_URL_BASE'), # 'http://localhost:11434'
                api_token=os.getenv('CRAWL4AI_MODEL_API_KEY'), # 'token'
                schema=StockInfo.schema(),
                extraction_type="schema",
                instruction="""Extraia todas as informações da página de ações, preenchendo todos os campos possíveis. 
                Organize as informações nos campos do modelo, incluindo:
                - Informações básicas da ação
                - Valor de mercado e da firma
                - Oscilações
                - Indicadores fundamentalistas
                - Dados do Balanço Patrimonial
                - Demonstrativos de Resultados

                Certifique-se de incluir dados numéricos e textuais relevantes.
                Use nomes claros nos campos extraídos, em especial indicadores_fundamentalistas."""
            ),
            bypass_cache=True,
        )
        return result.extracted_content


def format_complementary_stock_info(stock_data):
    """
    Formata dados complementares de ações de forma flexível.

    Args:
        stock_data (list): Lista de dicionários com informações da ação

    Returns:
        str: Relatório formatado com informações complementares
    """
    if not stock_data or not isinstance(stock_data, list):
        return "Nenhum dado disponível"

    # Pega o primeiro elemento (assumindo que é um único registro)
    data = stock_data[0]

    # Função auxiliar para formatar valores monetários
    def format_currency(value):
        try:
            return f"R$ {float(str(value).replace('.', '').replace(',', '.')):,.2f}"
        except (ValueError, TypeError):
            return value

    # Função auxiliar para extrair dados de forma segura
    def safe_get(dictionary, key, default='N/A'):
        return dictionary.get(key, default)

    # Preparando o relatório complementar
    report = f"""📊 Informações Complementares - {safe_get(data, 'papel', default='Ação')}

🏢 Detalhes da Empresa
- Empresa: {safe_get(data, 'empresa', default='N/A')}
- Setor: {safe_get(data, 'setor', default='N/A')}
- Subsetor: {safe_get(data, 'subsetor', default='N/A')}

💹 Cotação e Mercado
- Cotação Atual: {safe_get(data, 'cotacao', default='N/A')}
- Data Última Cotação: {safe_get(data, 'data_ultima_cotacao', default='N/A')}
- Valor de Mercado: {format_currency(safe_get(data, 'valor_mercado', default=0))}
- Número de Ações: {safe_get(data, 'numero_acoes', default='N/A')}

📈 Oscilações
"""

    # Adiciona oscilações de forma dinâmica
    oscilacoes = safe_get(data, 'oscilacoes', default={})
    for periodo, valor in oscilacoes.items():
        report += f"- {periodo.replace('_', ' ').title()}: {valor}\n"

    report += "\n📊 Indicadores Fundamentalistas\n"

    # Adiciona indicadores fundamentalistas de forma dinâmica
    indicadores = safe_get(data, 'indicadores_fundamentalistas', default={})
    for indicador, valor in indicadores.items():
        report += f"- {indicador.upper().replace('_', ' ')}: {valor}\n"

    report += "\n💰 Balanço Patrimonial\n"

    # Adiciona balanço patrimonial de forma dinâmica
    balanco = safe_get(data, 'balanco_patrimonial', default={})
    for conta, valor in balanco.items():
        report += f"- {conta.replace('_', ' ').title()}: {format_currency(valor)}\n"

    report += "\n📈 Demonstrativos de Resultados\n"

    # Adiciona demonstrativos de resultados para diferentes períodos
    resultados = safe_get(data, 'demonstrativos_resultados', default={})
    periodos = {
        '12 meses': ['receita_liq_ultimos_12_meses', 'ebit_ultimos_12_meses', 'lucro_liq_ultimos_12_meses'],
        '3 meses': ['receita_liq_ultimos_3_meses', 'ebit_ultimos_3_meses', 'lucro_liq_ultimos_3_meses']
    }

    for periodo, campos in periodos.items():
        report += f"\nPeríodo: {periodo}\n"
        for campo in campos:
            nome_formatado = campo.replace('_', ' ').replace('liq', 'líquido').title()
            report += f"- {nome_formatado}: {format_currency(resultados.get(campo, 'N/A'))}\n"

    return report


def get_complementary_data(ticker):
    """
    Obtém e prepara dados de análise de ações do Fundamentus.
    Encapsula a lógica assíncrona em uma função síncrona.

    Args:
        ticker (str): Código da ação (ex: "SLCE3")

    Returns:
        str: Dados formatados da ação
    """

    async def _async_get_data(ticker):
        url = f"https://fundamentus.com.br/detalhes.php?papel={ticker}"
        fundamentus_data = await extract_stock_info(url)
        fundamentus_json = json.loads(fundamentus_data)
        return format_complementary_stock_info(fundamentus_json)

    # Executa a função assíncrona e retorna o resultado
    return asyncio.run(_async_get_data(ticker))
