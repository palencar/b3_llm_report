import json
from get_info_yfinance import extract_yfinance_info
from get_info_crawl4ai import extract_stock_info, format_complementary_stock_info

def prepare_llm_investment_analysis_request(stock_info, complementary_info, analysis_date):
    """
    Prepara uma mensagem estruturada para análise de investimento por LLM

    Args:
        stock_info (str): Relatório detalhado do yfinance
        complementary_info (str): Relatório complementar de outra fonte
        analysis_date (str): Data no formato YYYY-MM-DD

    Returns:
        str: Mensagem completa para o LLM
    """
    prompt = f"""# Análise de Investimento
Data da Análise: {analysis_date} (YYYY-MM-DD)

## Instruções para Análise de Investimento

Você é um analista financeiro especializado em ações brasileiras. Forneça uma análise detalhada e objetiva das perspectivas de investimento para esta ação, considerando os dados fundamentalistas e de mercado.

### Horizontes de Análise
1. Curtíssimo Prazo (até 3 meses)
2. Curto Prazo (3-6 meses)
3. Médio Prazo (6-18 meses)

### Critérios de Análise
- Utilize APENAS os dados fornecidos nesta conversa
- Avalie cada horizonte considerando:
  * Tendências de mercado
  * Indicadores fundamentalistas
  * Oscilações históricas
  * Potencial de crescimento
  * Riscos setoriais e específicos da empresa

### Formato de Resposta

#### Resumo
- Recomendação Geral:
- Potencial de Retorno:
- Nível de Risco:

#### Análise por Horizonte

##### Curtíssimo Prazo (até 3 meses)
- Perspectiva:
- Gatilhos de Investimento:
- Pontos de Atenção:

##### Curto Prazo (3-6 meses)
- Perspectiva:
- Gatilhos de Investimento:
- Pontos de Atenção:

##### Médio Prazo (6-18 meses)
- Perspectiva Estratégica:
- Potencial de Crescimento:
- Desafios Identificados:

### Dados Detalhados

#### Informações Yfinance
{stock_info}

#### Informações Complementares
{complementary_info}

### Disclaimer
- Esta análise é baseada em dados disponíveis até a data atual
- Recomenda-se sempre complementar com análise própria e consulta a especialistas
"""
    return prompt
