def prepare_llm_investment_analysis_request(
    stock_info: str,
    complementary_info: str,
    analysis_date: str,
    cvm_info: str = "",
) -> str:
    cvm_section = f"\n#### Dados CVM (Demonstrativos Oficiais)\n{cvm_info}" if cvm_info else ""
    return f"""# Análise de Investimento
Data da Análise: {analysis_date} (YYYY-MM-DD)

## Instruções para Análise de Investimento

Você é um analista financeiro especializado em ações brasileiras. Forneça uma análise detalhada e objetiva das perspectivas de investimento para esta ação, considerando os dados fundamentalistas e de mercado.

### Horizontes de Análise
1. Curtíssimo Prazo (até 3 meses)
2. Curto Prazo (3-6 meses)
3. Médio Prazo (6-18 meses)

### Critérios de Análise
- Utilize APENAS os dados fornecidos nesta conversa
- Indique explicitamente o nível de confiança para cada conclusão com base na quantidade e qualidade dos dados disponíveis
- Caso a confiança seja limitada, forneça justificativas e descreva as limitações
- Avalie cada horizonte considerando:
  * Tendências de mercado
  * Indicadores fundamentalistas
  * Oscilações históricas
  * Potencial de crescimento
  * Riscos setoriais e específicos da empresa
- Cada conclusão deve ser apoiada por pelo menos dois elementos de evidência extraídos das seções de dados detalhados

### Formato de Resposta

#### Resumo
- Recomendação Geral:
- Potencial de Retorno:
- Nível de Risco:
- Incertezas e Limitações:

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
{cvm_section}
### Disclaimer
- Esta análise é baseada em dados disponíveis até a data atual
- Recomenda-se sempre complementar com análise própria e consulta a especialistas
- As respostas geradas podem variar dependendo da interpretação dos dados e dos critérios aplicados
"""
