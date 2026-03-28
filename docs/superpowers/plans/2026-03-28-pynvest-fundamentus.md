# pynvest Fundamentus Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Substituir crawl4ai por pynvest em `src/b3_report/sources/fundamentus.py`, mantendo a interface pública `get_complementary_data(ticker) -> str`.

**Architecture:** Reescrever `src/b3_report/sources/fundamentus.py` com pynvest. O módulo existente `tests/test_fundamentus.py` testa o ETL layer (`src/b3_etl/fundamentus.py`) — não é modificado. Os novos testes ficam em `tests/test_report_fundamentus.py`. `cli.py` e `prompts.py` não mudam.

**Tech Stack:** `pynvest>=0.1.2,<0.2` (requests + BeautifulSoup), `pandas`, `unittest.mock`

---

### Task 1: Implementar `get_complementary_data` com pynvest (TDD)

**Files:**
- Create: `tests/test_report_fundamentus.py`
- Modify: `src/b3_report/sources/fundamentus.py` (reescrever completamente)

- [ ] **Step 1: Instalar pynvest**

```bash
pip install "pynvest>=0.1.2,<0.2"
```

Verificar: `python -c "from pynvest.scrappers.fundamentus import Fundamentus; print('ok')`

- [ ] **Step 2: Escrever os 4 testes (todos devem falhar)**

Criar `tests/test_report_fundamentus.py`:

```python
"""Testes para src/b3_report/sources/fundamentus.py (pynvest)."""
import math
from unittest.mock import patch
import pandas as pd
import pytest

from b3_report.sources.fundamentus import get_complementary_data

_FAKE_ROW = {
    "nome_empresa": "PETROBRAS S.A.",
    "nome_setor": "Petróleo e Gás",
    "nome_subsetor": "Exploração e Produção",
    "vlr_cot": 49.41,
    "dt_ult_cot": "28/03/2026",
    "vlr_min_52_sem": 30.10,
    "vlr_max_52_sem": 49.44,
    "vol_med_neg_2m": 98765432.0,
    "vlr_mercado": 636800000000.0,
    "vlr_firma": 700000000000.0,
    "num_acoes": 13000000000,
    "dt_ult_balanco_proc": "31/12/2024",
    "vlr_ind_p_sobre_l": 6.05,
    "vlr_ind_p_sobre_vp": 1.20,
    "vlr_ind_p_sobre_ebit": 4.10,
    "vlr_ind_psr": 0.90,
    "vlr_ind_p_sobre_ativ": 0.50,
    "vlr_ind_p_sobre_cap_giro": math.nan,   # deve ser omitido
    "vlr_ind_p_sobre_ativ_circ_liq": math.nan,
    "vlr_ind_ev_sobre_ebitda": 3.50,
    "vlr_ind_ev_sobre_ebit": 4.80,
    "vlr_ind_div_yield": 0.0791,
    "vlr_ind_lpa": 8.16,
    "vlr_ind_vpa": 41.00,
    "vlr_ind_roe": 0.20,
    "vlr_ind_roic": 0.15,
    "vlr_ind_margem_bruta": 0.45,
    "vlr_ind_margem_ebit": 0.30,
    "vlr_ind_margem_liq": 0.15,
    "vlr_ind_ebit_sobre_ativo": 0.12,
    "vlr_ind_giro_ativos": 0.35,
    "pct_cresc_rec_liq_ult_5a": 0.08,
    "vlr_ativo": 900000000000.0,
    "vlr_disponibilidades": 50000000000.0,
    "vlr_ativ_circulante": 150000000000.0,
    "vlr_divida_bruta": 300000000000.0,
    "vlr_divida_liq": 250000000000.0,
    "vlr_patrim_liq": 367510000000.0,
    "vlr_liquidez_corr": 1.20,
    "vlr_ind_divida_bruta_sobre_patrim": 0.82,
    "vlr_ind_giro_ativos": 0.35,
    "vlr_receita_liq_ult_12m": 500000000000.0,
    "vlr_ebit_ult_12m": 150000000000.0,
    "vlr_lucro_liq_ult_12m": 75000000000.0,
    "vlr_receita_liq_ult_3m": 120000000000.0,
    "vlr_ebit_ult_3m": 35000000000.0,
    "vlr_lucro_liq_ult_3m": 18000000000.0,
    "pct_var_dia": 0.01,
    "pct_var_mes": 0.03,
    "pct_var_30d": 0.05,
    "pct_var_12m": 0.12,
    "pct_var_ano_a0": 0.08,
    "pct_var_ano_a1": -0.05,
    "pct_var_ano_a2": 0.20,
}

_FAKE_DF = pd.DataFrame([_FAKE_ROW])

_PATCH_TARGET = "b3_report.sources.fundamentus.Fundamentus"


def test_get_complementary_data_retorna_texto():
    """Com DataFrame válido, retorna string com ticker e seções esperadas."""
    with patch(_PATCH_TARGET) as mock_cls:
        mock_cls.return_value.coleta_indicadores_de_ativo.return_value = _FAKE_DF
        result = get_complementary_data("PETR4")
    assert "PETR4" in result
    assert "Dados de Mercado" in result
    assert "Múltiplos de Valuation" in result
    assert "Rentabilidade" in result
    assert "Balanço e DRE (Fundamentus)" in result
    assert "Oscilações" in result
    assert "PETROBRAS S.A." in result
    assert "6.05" in result  # P/L presente


def test_get_complementary_data_omite_nan():
    """Colunas com NaN não aparecem na saída."""
    with patch(_PATCH_TARGET) as mock_cls:
        mock_cls.return_value.coleta_indicadores_de_ativo.return_value = _FAKE_DF
        result = get_complementary_data("PETR4")
    assert "P/Cap.Giro" not in result
    assert "P/Ativ.Circ.Liq" not in result


def test_get_complementary_data_excecao():
    """Exception no pynvest → retorna '' sem propagar."""
    with patch(_PATCH_TARGET) as mock_cls:
        mock_cls.return_value.coleta_indicadores_de_ativo.side_effect = Exception("timeout")
        result = get_complementary_data("PETR4")
    assert result == ""


def test_get_complementary_data_df_vazio():
    """DataFrame vazio → retorna ''."""
    with patch(_PATCH_TARGET) as mock_cls:
        mock_cls.return_value.coleta_indicadores_de_ativo.return_value = pd.DataFrame()
        result = get_complementary_data("PETR4")
    assert result == ""
```

- [ ] **Step 3: Rodar testes — confirmar que falham**

```bash
pytest tests/test_report_fundamentus.py -v
```

Esperado: 4 FAILs com `ImportError` ou `AttributeError` (módulo ainda usa crawl4ai).

- [ ] **Step 4: Reescrever `src/b3_report/sources/fundamentus.py`**

Substituir o conteúdo completo do arquivo:

```python
"""Source Fundamentus: indicadores de mercado via pynvest."""
import logging
import math

import pandas as pd
from pynvest.scrappers.fundamentus import Fundamentus

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mapeamento seção → [(label, coluna_pynvest)]
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _val(row: pd.Series, col: str):
    """Return value as str, or None if column absent or NaN."""
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


# ---------------------------------------------------------------------------
# Interface pública
# ---------------------------------------------------------------------------


def get_complementary_data(ticker: str) -> str:
    """Return formatted Fundamentus data for ticker via pynvest, or '' on failure."""
    try:
        df = Fundamentus().coleta_indicadores_de_ativo(ticker)
        if df is None or df.empty:
            return ""
        return _format(ticker, df)
    except Exception as e:
        _logger.warning("Fundamentus pynvest error for ticker=%s: %s", ticker, e)
        return ""
```

- [ ] **Step 5: Rodar testes — confirmar que passam**

```bash
pytest tests/test_report_fundamentus.py -v
```

Esperado: 4 PASSes.

- [ ] **Step 6: Rodar suite completa — sem regressões**

```bash
pytest tests/ -q
```

Esperado: todos passando (os testes em `test_fundamentus.py` testam `b3_etl.fundamentus`, não foram tocados).

- [ ] **Step 7: Commit**

```bash
git add src/b3_report/sources/fundamentus.py tests/test_report_fundamentus.py
git commit -m "feat: substitui crawl4ai por pynvest em get_complementary_data"
```

---

### Task 2: Atualizar `requirements.txt`

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Atualizar `requirements.txt`**

```
yfinance==0.2.49
pynvest>=0.1.2,<0.2
openai==1.54.3
python-dotenv>=1.0,<2.0
```

(Remover `Crawl4AI==0.3.731`, adicionar `pynvest>=0.1.2,<0.2`)

- [ ] **Step 2: Rodar suite completa — confirmar que nada quebrou**

```bash
pytest tests/ -q
```

Esperado: todos passando.

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "chore: remove Crawl4AI, adiciona pynvest>=0.1.2,<0.2"
```
