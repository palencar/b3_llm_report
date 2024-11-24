## Sobre
Este script utiliza a API OpenAI para obter informações e perspectivas sobre papeis negociados na B3, utilizando informações obtidas a partir da biblioteca yfinance e do site fundamentus.com.br através do scraper crawl4ai.

As informações são enviadas a um modelo LLM (Large Language Model) local no Ollama (llama3.1:8b) para obter uma visão geral da situação atual e perspectivas futuras.

# Instalação e configuração

Para usar esse script, você precisará ter:

- Uma instância do Ollama configurada com um modelo de LLM local (usamos aqui o llama3.1:8b customizado com 8k tokens de contexto).
- A biblioteca yfinance instalada para obter informações de mercado.
- O scraper crawl4ai instalado para coletar dados dos papeis negociados no site fundamentus.com.br.

## Dependências

O ideal é criar um ambiente Python próprio (como venv ou miniconda) e instalar as dependências necessárias. Isso pode ser feito executando os comandos abaixo:
```
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Configuração
As configurações necessárias estão no arquivo `.env`. Certifique-se de que as seguintes variáveis estejam definidas:

* `CRAWL4AI_MODEL_API_KEY`: Chave de API para o modelo usado no Crawl4ai. Usamos apenas "token", pois não pode ser nula.
* `CRAWL4AI_MODEL_PROVIDER`: Provider usado no Crwal4ai. Usamos aqui o Ollama e o modelo local "llama3.1:8b-8k", portanto "ollama/llama3.1:8b-8k".
* `CRAWL4AI_MODEL_URL_BASE`: URL base da instância do Ollama usada no Crwal4ai (padrão: "http://localhost:11434")
* `OPENAI_URL_BASE`: URL base da API OpenAI usado pelo script (padrão: "http://localhost:11434/v1")
* `OPENAI_MODEL_NAME`: Nome do modelo LLM a ser utilizado para análise.

### Exemplo de uso

```bash
python main.py ACAO3
```

## Alerta
**ISTO É APENAS UM EXPERIMENTO E NÃO DEVE SER USADO COMO RECOMENDAÇÃO DE INVESTIMENTO**.

### Exemplo de Resposta

#### Resumo

*   **Recomendação Geral:** Strong Buy, devido ao desempenho recente da empresa e às perspectivas favoráveis do setor de energia elétrica.
*   **Potencial de Retorno:** 20% - 30% ao longo dos próximos 12 meses.
*   **Nível de Risco:** Baixo, considerando a estabilidade financeira da empresa e o desempenho histórico.

#### Análise por Horizonte

##### Curtíssimo Prazo (até 3 meses)

*   **Perspectiva:** Forte tendência ascendente, com potencial de aumento do preço.
*   **Gatilhos de Investimento:**
    *   Aumentos nos preços das commodities, como o petróleo e a gás natural, que impactam positivamente os negócios da empresa.
    *   Melhoria na política energética brasileira, com enfoque em fontes de energia renovável.
*   **Pontos de Atenção:**
    *   Aflorar de risco geopolítico no setor de energia, como mudanças nas relações internacionais que afetam a demanda por energia.
    *   Impacto negativo da inflação e taxas de juros mais altas sobre as finanças dos consumidores.

##### Curto Prazo (3-6 meses)

*   **Perspectiva:** Continuação da tendência ascendente, com possibilidade de ajuste nos preços.
*   **Gatilhos de Investimento:**
    *   Implementação de projetos de energia renovável e eficiência energética que aumentem a capacidade da empresa.
    *   Fortalecimento da competitividade da empresa em termos de custo e eficiência, tornando-a mais atraente para os investidores.
*   **Pontos de Atenção:**
    *   Desafios legais ou regulatórios que possam afetar negativamente a operação da empresa.
    *   Impacto do mercado global sobre as finanças e estratégia de negócios da empresa.

##### Médio Prazo (6-18 meses)

*   **Perspectiva Estratégica:** Aumento sustentado nos resultados financeiros, com expansão dos negócios.
*   **Potencial de Crescimento:** 30% - 50% ao longo das próximas 12 a 24 meses.
*   **Desafios Identificados:**
    *   Aumento da competição por recursos naturais e energia, afetando os custos e lucros da empresa.
    *   Mudanças nas políticas governamentais que impactem negativamente os setores de energia elétrica.




