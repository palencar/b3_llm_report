# Design — Substituição crawl4ai por pynvest no Fundamentus

**Data:** 2026-03-28
**Escopo:** Reescrever `src/b3_report/sources/fundamentus.py` substituindo crawl4ai/LLM por pynvest (requests + BeautifulSoup). Interface pública inalterada.

---

## Problema

`get_complementary_data` depende de crawl4ai (browser headless) + uma chamada LLM adicional apenas para parsear HTML do Fundamentus. Custo e complexidade desproporcionais para a tarefa.

## Solução

Substituir por `pynvest`, que faz requests HTTP diretas + BeautifulSoup. Sem browser, sem LLM, mesma fonte de dados.

---

## Arquivos modificados

| Arquivo | Ação |
|---------|------|
| `src/b3_report/sources/fundamentus.py` | Reescrever — remover crawl4ai, implementar pynvest |
| `requirements.txt` | Remover `Crawl4AI==0.3.731`, adicionar `pynvest>=0.1.2,<0.2` |
| `tests/test_fundamentus.py` | Criar — testes com mock do pynvest |

`cli.py` e `prompts.py` não mudam.

---

## Implementação de `fundamentus.py`

### Interface pública (inalterada)

```python
def get_complementary_data(ticker: str) -> str
```

Retorna string formatada com dados do Fundamentus, ou `""` em caso de falha.

### Estrutura interna

```python
import logging
import math
import pandas as pd
from pynvest.scrappers.fundamentus import Fundamentus

_logger = logging.getLogger(__name__)

# Seções: lista de (label_coluna, coluna_pynvest)
_SECAO_MERCADO = [
    ("Empresa", "nome_empresa"),
    ("Setor", "nome_setor"),
    ("Subsetor", "nome_subsetor"),
    ("Cotação", "vlr_cot"),
    ("Data Últ. Cotação", "dt_ult_cot"),
    ("Mín. 52 sem.", "vlr_min_52_sem"),
    ("Máx. 52 sem.", "vlr_max_52_sem"),
    ("Vol. Méd. 2m", "vol_med_neg_2m"),
    ("Valor de Mercado", "vlr_mercado"),
    ("Valor da Firma (EV)", "vlr_firma"),
    ("Nº de Ações", "num_acoes"),
    ("Últ. Balanço", "dt_ult_balanco_proc"),
]

_SECAO_MULTIPLOS = [
    ("P/L", "vlr_ind_p_sobre_l"),
    ("P/VP", "vlr_ind_p_sobre_vp"),
    ("P/EBIT", "vlr_ind_p_sobre_ebit"),
    ("PSR", "vlr_ind_psr"),
    ("P/Ativo", "vlr_ind_p_sobre_ativ"),
    ("P/Cap.Giro", "vlr_ind_p_sobre_cap_giro"),
    ("P/Ativ.Circ.Liq", "vlr_ind_p_sobre_ativ_circ_liq"),
    ("EV/EBITDA", "vlr_ind_ev_sobre_ebitda"),
    ("EV/EBIT", "vlr_ind_ev_sobre_ebit"),
    ("Div. Yield", "vlr_ind_div_yield"),
    ("LPA", "vlr_ind_lpa"),
    ("VPA", "vlr_ind_vpa"),
]

_SECAO_RENTABILIDADE = [
    ("ROE", "vlr_ind_roe"),
    ("ROIC", "vlr_ind_roic"),
    ("Margem Bruta", "vlr_ind_margem_bruta"),
    ("Margem EBIT", "vlr_ind_margem_ebit"),
    ("Margem Líquida", "vlr_ind_margem_liq"),
    ("EBIT/Ativo", "vlr_ind_ebit_sobre_ativo"),
    ("Giro do Ativo", "vlr_ind_giro_ativos"),
    ("Cresc. Rec. 5a", "pct_cresc_rec_liq_ult_5a"),
]

_SECAO_BALANCO_DRE = [
    ("Ativo Total", "vlr_ativo"),
    ("Disponibilidades", "vlr_disponibilidades"),
    ("Ativo Circulante", "vlr_ativ_circulante"),
    ("Dívida Bruta", "vlr_divida_bruta"),
    ("Dívida Líquida", "vlr_divida_liq"),
    ("Patrimônio Líquido", "vlr_patrim_liq"),
    ("Liquidez Corrente", "vlr_liquidez_corr"),
    ("Dív.Bruta/Patrim.", "vlr_ind_divida_bruta_sobre_patrim"),
    ("Receita Líq. 12m", "vlr_receita_liq_ult_12m"),
    ("EBIT 12m", "vlr_ebit_ult_12m"),
    ("Lucro Líq. 12m", "vlr_lucro_liq_ult_12m"),
    ("Receita Líq. 3m", "vlr_receita_liq_ult_3m"),
    ("EBIT 3m", "vlr_ebit_ult_3m"),
    ("Lucro Líq. 3m", "vlr_lucro_liq_ult_3m"),
]

_SECAO_OSCILACOES = [
    ("Dia", "pct_var_dia"),
    ("Mês", "pct_var_mes"),
    ("30 dias", "pct_var_30d"),
    ("12 meses", "pct_var_12m"),
    ("Ano (a0)", "pct_var_ano_a0"),
    ("Ano -1", "pct_var_ano_a1"),
    ("Ano -2", "pct_var_ano_a2"),
]
```

### Função de formatação

```python
def _val(row: pd.Series, col: str) -> str:
    """Extrai valor da Series; retorna None se ausente ou NaN."""
    if col not in row.index:
        return None
    v = row[col]
    if isinstance(v, float) and math.isnan(v):
        return None
    return str(v)


def _format_section(title: str, fields: list, row: pd.Series) -> str:
    lines = [title]
    for label, col in fields:
        v = _val(row, col)
        if v is not None:
            lines.append(f"- {label}: {v}")
    return "\n".join(lines) if len(lines) > 1 else ""


def _format(ticker: str, df: pd.DataFrame) -> str:
    row = df.iloc[0]
    sections = [
        _format_section("Dados de Mercado", _SECAO_MERCADO, row),
        _format_section("Múltiplos de Valuation", _SECAO_MULTIPLOS, row),
        _format_section("Rentabilidade", _SECAO_RENTABILIDADE, row),
        _format_section("Balanço e DRE (Fundamentus)", _SECAO_BALANCO_DRE, row),
        _format_section("Oscilações", _SECAO_OSCILACOES, row),
    ]
    body = "\n\n".join(s for s in sections if s)
    return f"Informações Complementares — {ticker}\n\n{body}"
```

### Degradação graciosa

```python
def get_complementary_data(ticker: str) -> str:
    try:
        df = Fundamentus().coleta_indicadores_de_ativo(ticker)
        if df is None or df.empty:
            return ""
        return _format(ticker, df)
    except Exception as e:
        _logger.warning("Fundamentus pynvest error for ticker=%s: %s", ticker, e)
        return ""
```

---

## `requirements.txt` — antes e depois

```diff
 yfinance==0.2.49
-Crawl4AI==0.3.731
+pynvest>=0.1.2,<0.2
 openai==1.54.3
 python-dotenv>=1.0,<2.0
```

---

## Testes — `tests/test_fundamentus.py`

Fixtures com `unittest.mock.patch` em `pynvest.scrappers.fundamentus.Fundamentus.coleta_indicadores_de_ativo`.

| Teste | O que verifica |
|-------|----------------|
| `test_get_complementary_data_retorna_texto` | Com DataFrame sintético, retorna string com ticker e seções esperadas |
| `test_get_complementary_data_omite_nan` | Colunas com NaN não aparecem na saída |
| `test_get_complementary_data_excecao` | Exception no pynvest → retorna `""` sem propagar |
| `test_get_complementary_data_df_vazio` | DataFrame vazio → retorna `""` |

### Fixture DataFrame sintético

```python
import math
import pandas as pd

_FAKE_ROW = {
    "nome_empresa": "PETROBRAS S.A.",
    "nome_setor": "Petróleo e Gás",
    "nome_subsetor": "Exploração e Produção",
    "vlr_cot": 49.41,
    "vlr_ind_p_sobre_l": 6.05,
    "vlr_ind_roe": 0.20,
    "vlr_ind_div_yield": 0.0791,
    "vlr_ind_margem_liq": 0.15,
    "pct_var_dia": 0.01,
    "vlr_ind_p_sobre_vp": math.nan,  # deve ser omitido
}

_FAKE_DF = pd.DataFrame([_FAKE_ROW])
```

---

## O que não muda

- `src/b3_report/cli.py`
- `src/b3_report/prompts.py`
- Toda a stack CVM e yfinance
- Schema DuckDB

---

## Critérios de aceitação

1. `get_complementary_data("PETR4")` retorna string com seções "Dados de Mercado", "Múltiplos de Valuation", etc.
2. Colunas NaN omitidas silenciosamente
3. Exception no pynvest → retorna `""` sem propagar
4. `python main.py PETR4` funciona com a seção Fundamentus populada
5. `pytest tests/test_fundamentus.py -v` — todos os testes passam sem rede
