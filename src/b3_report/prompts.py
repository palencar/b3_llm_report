def prepare_llm_investment_analysis_request(
    stock_info: str,
    complementary_info: str,
    analysis_date: str,
    cvm_info: str = "",
    history_reports: str = "",
) -> str:
    cvm_section = f"\n#### Dados CVM (Demonstrativos Oficiais)\n{cvm_info}\n" if cvm_info else ""
    history_section = (
        f"\n#### Histórico de Relatórios Recentes\n{history_reports}\n"
        if history_reports
        else ""
    )
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
- Responda integralmente em português brasileiro claro, direto e natural
- Não use rótulos ou termos em inglês na resposta final
- Quando precisar classificar a recomendação, use apenas: Compra, Manutenção, Venda, Compra em Correção, Neutra
- Prefira termos em português como: potencial de valorização, correção, preço-alvo, consenso de analistas, múltiplos, projeção de lucro
- Evite expressões imprecisas ou inadequadas para ações, como: "renda fixa via dividendos", "debitabilidade financeira", "upside", "downside", "pullback", "case", "topo histórico" quando bastar "máxima de 52 semanas"
- Quando necessário, prefira estas substituições:
  * "perfil de renda/dividendos" no lugar de "renda fixa via dividendos"
  * "pressão da dívida" ou "alavancagem financeira" no lugar de "debitabilidade financeira"
  * "potencial de valorização" no lugar de "upside"
  * "potencial de queda" no lugar de "downside"
  * "correção" ou "recuo" no lugar de "pullback"
  * "tese" ou "cenário" no lugar de "case"
- Não infira cenário macroeconômico, regulação, fluxo institucional, movimento setorial futuro, juros, câmbio ou catalisadores externos sem dado explícito nas seções fornecidas
- Se um ponto depender de informação externa não presente nos dados, registre a limitação em vez de extrapolar
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
- Siga EXATAMENTE a estrutura e a ordem abaixo
- Não adicione seções, subseções, campos ou observações extras
- Não renomeie títulos, subtítulos ou rótulos
- Não inclua campos adicionais como "Nível de Confusão", "Confiança Justificativa", "Resumo Executivo" ou equivalentes
- O texto final deve começar pela seção "#### Identificação"
- No campo "Empresa", informe o nome da empresa conforme os dados fornecidos; se não houver nome claro, use o ticker disponível
- No campo "Data da Análise", reproduza exatamente: {analysis_date}
- Em cada horizonte, mantenha apenas os campos listados no modelo abaixo
- Se faltar dado para algum campo, preserve o rótulo e explique a limitação no próprio campo
- Use sempre markdown simples com os mesmos cabeçalhos e bullets do modelo abaixo
- Seja conciso: no máximo 2 frases por campo
- Priorize objetividade e elimine repetição entre horizontes
- Limite o relatório inteiro a aproximadamente 350 palavras
- Padronize a apresentação numérica:
  * preços, preço-alvo e valores monetários unitários: 2 casas decimais
  * múltiplos e indicadores por ação: até 2 casas decimais
  * percentuais: até 1 casa decimal
  * valores muito grandes podem ser abreviados em bilhões ou milhões quando isso melhorar a leitura
- Evite precisão excessiva como 32.4049, 2.83763 ou percentuais com várias casas decimais

#### Identificação
- Empresa:
- Data da Análise: {analysis_date}

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
{history_section}
"""
