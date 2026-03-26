# Design — Integração CVM no Relatório LLM

**Data:** 2026-03-26
**Escopo:** Adicionar dados oficiais CVM (DFP/ITR) como terceira seção do prompt do relatório LLM, mantendo yfinance e Fundamentus existentes

---

## Contexto

O relatório LLM (`src/b3_report/cli.py`) atualmente combina:
1. **yfinance** — preço, métricas de mercado, recomendações de analistas
2. **Fundamentus** (crawl4ai) — indicadores fundamentalistas, balanço e DRE via scraping

Os dados CVM (`cvm_statements`, `cvm_companies`, `ticker_map`) estão no DuckDB e expõem demonstrativos financeiros oficiais dos últimos 3 anos (DFP anual + ITR trimestral). A integração adiciona esses dados como terceira seção, complementando com histórico oficial de 3 anos — sem substituir o Fundamentus, que permanece como fonte de indicadores de mercado.

---

## Arquitetura

### Novos/modificados arquivos

| Arquivo | Ação |
|---------|------|
| `src/b3_report/sources/cvm.py` | Criar — `get_cvm_data(ticker, db_path) -> str` |
| `src/b3_report/prompts.py` | Modificar — adicionar parâmetro `cvm_info` e seção no prompt |
| `src/b3_report/cli.py` | Modificar — chamar `get_cvm_data` e passar ao prompt builder |
| `tests/test_report_cvm.py` | Criar — testes unitários |

### Sem novas dependências

Usa apenas `b3_storage.db.connect` (já disponível) e stdlib (`re`).

---

## Módulo `src/b3_report/sources/cvm.py`

### Função pública

```python
def get_cvm_data(ticker: str, db_path: str) -> str
```

Retorna string formatada com demonstrativos CVM para o ticker, ou `""` se dados indisponíveis.

### Filtro de contas (nível 1-2)

Inclui apenas contas com 0 ou 1 ponto no `account_code`:
```python
LENGTH(account_code) - LENGTH(REPLACE(account_code, '.', '')) <= 1
```

Exemplos incluídos: `"1"`, `"1.01"`, `"2"`, `"3.01"`
Exemplos excluídos: `"1.01.01"`, `"3.02.01.02"`

### SQL

```sql
SELECT s.period, s.report_type, s.account_code, s.account_name, s.value, s.currency
FROM cvm_statements s
JOIN cvm_companies c ON c.cnpj = s.cnpj
JOIN ticker_map t    ON regexp_replace(c.cnpj, '[^0-9]', '', 'g') = t.cnpj
WHERE t.ticker = ?
  AND s.report_type IN ('BPA', 'BPP', 'DRE', 'DFC_MI', 'DFC_MD')
  AND LENGTH(s.account_code) - LENGTH(REPLACE(s.account_code, '.', '')) <= 1
  AND EXTRACT(year FROM s.period) >= EXTRACT(year FROM CURRENT_DATE) - 3
ORDER BY s.report_type, s.account_code, s.period
```

### Formato de saída

```
Demonstrativos CVM Oficiais — PETR4

Balanço Patrimonial Ativo (BPA)
- Ativo Total (1): 2022=R$900.000.000 | 2023=R$950.000.000 | 2024=R$1.000.000.000
- Ativo Circulante (1.01): 2022=R$200.000.000 | ...

Balanço Patrimonial Passivo (BPP)
- ...

Demonstração do Resultado (DRE)
- ...

Fluxo de Caixa (DFC)
- ...
```

- Valores formatados como `R$NNN.NNN.NNN` (inteiros, sem decimais)
- Tipos DFC_MI e DFC_MD são apresentados sob o mesmo cabeçalho "Fluxo de Caixa (DFC)" — empresa usa um ou outro
- Contas sem dados num período são omitidas silenciosamente

### Degradação graciosa

| Situação | Comportamento |
|----------|--------------|
| DuckDB não encontrado | retorna `""` |
| Ticker não mapeado em `ticker_map` | retorna `""` |
| Sem dados CVM para o ticker | retorna `""` |
| Erro de query | loga e retorna `""` |

---

## Modificação em `src/b3_report/prompts.py`

Assinatura atual:
```python
def prepare_llm_investment_analysis_request(
    stock_info: str,
    complementary_info: str,
    analysis_date: str,
) -> str
```

Nova assinatura:
```python
def prepare_llm_investment_analysis_request(
    stock_info: str,
    complementary_info: str,
    analysis_date: str,
    cvm_info: str = "",
) -> str
```

Nova seção adicionada ao final de `### Dados Detalhados`, após `#### Informações Complementares`:

```python
cvm_section = f"\n#### Dados CVM (Demonstrativos Oficiais)\n{cvm_info}" if cvm_info else ""
```

O parâmetro tem default `""` para manter compatibilidade retroativa com chamadas existentes.

---

## Modificação em `src/b3_report/cli.py`

```python
from b3_report.sources.cvm import get_cvm_data

# dentro de run_report():
cvm_report = get_cvm_data(normalized_symbol, config.db_path)
llm_prompt = prepare_llm_investment_analysis_request(
    yfinance_report,
    complementary_report,
    analysis_date,
    cvm_info=cvm_report,
)
```

---

## Testes

Arquivo: `tests/test_report_cvm.py`

Fixtures em memória com DuckDB real (padrão do projeto).

| Teste | O que verifica |
|-------|---------------|
| `test_get_cvm_data_retorna_texto` | Com dados no DuckDB, retorna string não vazia com ticker e nomes de contas |
| `test_get_cvm_data_filtra_nivel_1_2` | Contas de nível ≥3 (`"1.01.01"`) não aparecem na saída |
| `test_get_cvm_data_tendencia_3_anos` | Dados de 3 anos aparecem no formato `2022=... | 2023=... | 2024=...` |
| `test_get_cvm_data_ticker_nao_encontrado` | Ticker sem mapeamento retorna `""` |
| `test_get_cvm_data_db_ausente` | `db_path` inexistente retorna `""` sem exceção |
| `test_prompt_inclui_secao_cvm` | Quando `cvm_info != ""`, seção `#### Dados CVM` aparece no prompt |
| `test_prompt_omite_secao_cvm` | Quando `cvm_info == ""`, seção CVM não aparece no prompt |

---

## O que não muda

- Lógica de yfinance e Fundamentus
- Interface pública de `run_report`
- Schema DuckDB
- MCP server

---

## Critérios de aceitação

1. `run_report("PETR4")` inclui seção CVM quando DuckDB populado
2. `run_report("PETR4")` funciona sem erro quando DuckDB ausente (CVM omitida)
3. Contas de nível ≥3 não aparecem na seção CVM
4. Dados de 3 anos aparecem no formato de tendência por linha
5. `pytest tests/test_report_cvm.py -v` — todos os testes passam sem rede ou banco real
