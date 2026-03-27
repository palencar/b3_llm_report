# CVM Report Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar dados oficiais CVM como terceira seção do relatório LLM, consultando o DuckDB diretamente sem depender do MCP server.

**Architecture:** Nova source `src/b3_report/sources/cvm.py` consulta DuckDB via `b3_storage.db.connect`, filtra contas nível 1-2 dos últimos 3 anos e formata como texto. `prompts.py` recebe `cvm_info: str = ""` e insere seção opcional. `cli.py` chama a nova source e repassa ao prompt builder.

**Tech Stack:** DuckDB (`b3_storage.db`), Python stdlib (`os`, `collections.defaultdict`).

---

## Estrutura de arquivos

| Arquivo | Ação |
|---------|------|
| `src/b3_report/sources/cvm.py` | Criar — `get_cvm_data` + helpers privados |
| `tests/test_report_cvm.py` | Criar — 7 testes (5 source + 2 prompt) |
| `src/b3_report/prompts.py` | Modificar — adicionar parâmetro `cvm_info` e seção no prompt |
| `src/b3_report/cli.py` | Modificar — chamar `get_cvm_data` e passar ao prompt |

---

## Task 1: Source `get_cvm_data` + testes

**Files:**
- Create: `src/b3_report/sources/cvm.py`
- Create: `tests/test_report_cvm.py`

### Contexto de codebase

`tests/conftest.py` adiciona `src/` ao `sys.path`. Use `from b3_storage.schema import SCHEMA_SQL` e `from b3_storage.db import connect` para inicializar DuckDB em memória nos testes — mesmo padrão de `tests/test_cvm.py`.

Schema relevante (em `src/b3_storage/schema.py`):
- `ticker_map(cnpj TEXT, ticker TEXT, name TEXT, updated_at TIMESTAMP)` — cnpj só com dígitos
- `cvm_companies(cnpj TEXT, ...)` — cnpj formatado com pontuação
- `cvm_statements(cnpj, period DATE, report_type, account_code, account_name, value DOUBLE, currency, source, fetched_at, PRIMARY KEY(cnpj, period, report_type, account_code, source))`

O join normaliza CNPJ: `regexp_replace(c.cnpj, '[^0-9]', '', 'g') = t.cnpj`.

Filtro nível 1-2: `LENGTH(account_code) - LENGTH(REPLACE(account_code, '.', '')) <= 1`
- Mantém: `"1"`, `"1.01"`, `"3.01"`
- Descarta: `"1.01.01"`, `"3.02.01.02"`

- [ ] **Step 1: Criar `tests/test_report_cvm.py` com os testes da source**

```python
"""Testes para src/b3_report/sources/cvm.py e integração no prompt."""
import pytest
from datetime import datetime, timezone, date

from b3_storage.schema import SCHEMA_SQL
from b3_storage.db import connect
from b3_report.sources.cvm import get_cvm_data


def _init_con(db_path: str):
    con = connect(db_path, read_only=False)
    for stmt in SCHEMA_SQL.split(";"):
        s = stmt.strip()
        if s:
            con.execute(s)
    return con


def _seed_data(con) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    con.execute(
        "INSERT INTO ticker_map VALUES (?, ?, ?, ?)",
        ["33000167000101", "PETR4", "PETROBRAS", now],
    )
    con.execute(
        "INSERT INTO cvm_companies VALUES (?, ?, ?, ?)",
        ["33.000.167/0001-01", "PETROBRAS S.A.", "9512", now],
    )
    for year in (2022, 2023, 2024):
        period = date(year, 12, 31)
        con.execute(
            "INSERT INTO cvm_statements VALUES (?,?,?,?,?,?,?,?,?)",
            ["33.000.167/0001-01", period, "BPA", "1", "Ativo Total",
             float(100_000_000 * year), "REAL", "cvm_dfp", now],
        )
        con.execute(
            "INSERT INTO cvm_statements VALUES (?,?,?,?,?,?,?,?,?)",
            ["33.000.167/0001-01", period, "BPA", "1.01", "Ativo Circulante",
             float(30_000_000 * year), "REAL", "cvm_dfp", now],
        )
        # nível 3 — deve ser filtrado
        con.execute(
            "INSERT INTO cvm_statements VALUES (?,?,?,?,?,?,?,?,?)",
            ["33.000.167/0001-01", period, "BPA", "1.01.01", "Caixa e Equivalentes",
             float(10_000_000 * year), "REAL", "cvm_dfp", now],
        )
        con.execute(
            "INSERT INTO cvm_statements VALUES (?,?,?,?,?,?,?,?,?)",
            ["33.000.167/0001-01", period, "DRE", "3.01", "Receita Líquida",
             float(50_000_000 * year), "REAL", "cvm_dfp", now],
        )
    con.execute("COMMIT")


def test_get_cvm_data_retorna_texto(tmp_path):
    db = str(tmp_path / "t.duckdb")
    con = _init_con(db)
    _seed_data(con)
    con.close()
    result = get_cvm_data("PETR4", db)
    assert result != ""
    assert "PETR4" in result
    assert "Ativo Total" in result


def test_get_cvm_data_filtra_nivel_1_2(tmp_path):
    db = str(tmp_path / "t.duckdb")
    con = _init_con(db)
    _seed_data(con)
    con.close()
    result = get_cvm_data("PETR4", db)
    assert "Ativo Total" in result          # nível 1: presente
    assert "Ativo Circulante" in result     # nível 2: presente
    assert "Caixa e Equivalentes" not in result  # nível 3: filtrado


def test_get_cvm_data_tendencia_3_anos(tmp_path):
    db = str(tmp_path / "t.duckdb")
    con = _init_con(db)
    _seed_data(con)
    con.close()
    result = get_cvm_data("PETR4", db)
    assert "2022=" in result
    assert "2023=" in result
    assert "2024=" in result
    assert "|" in result


def test_get_cvm_data_ticker_nao_encontrado(tmp_path):
    db = str(tmp_path / "t.duckdb")
    con = _init_con(db)
    _seed_data(con)
    con.close()
    assert get_cvm_data("XXXX3", db) == ""


def test_get_cvm_data_db_ausente(tmp_path):
    assert get_cvm_data("PETR4", str(tmp_path / "nao_existe.duckdb")) == ""
```

- [ ] **Step 2: Executar e confirmar FAIL**

```bash
cd /home/paulo/Projetos/b3_llm_report && python -m pytest tests/test_report_cvm.py -v -k "get_cvm" 2>&1 | head -15
```

Expected: `ImportError` — `b3_report.sources.cvm` não existe ainda.

- [ ] **Step 3: Criar `src/b3_report/sources/cvm.py`**

```python
"""Source CVM: busca demonstrativos oficiais do DuckDB para o relatório LLM."""
import os
from collections import defaultdict

from b3_storage.db import connect


_TYPE_LABELS = {
    "BPA": "Balanço Patrimonial Ativo (BPA)",
    "BPP": "Balanço Patrimonial Passivo (BPP)",
    "DRE": "Demonstração do Resultado (DRE)",
    "DFC_MI": "Fluxo de Caixa (DFC)",
    "DFC_MD": "Fluxo de Caixa (DFC)",
}

_QUERY = """
    SELECT s.period, s.report_type, s.account_code, s.account_name, s.value
    FROM cvm_statements s
    JOIN cvm_companies c ON c.cnpj = s.cnpj
    -- ticker_map.cnpj é dígitos apenas (normalizado por parse_b3_results no ingest)
    JOIN ticker_map t    ON regexp_replace(c.cnpj, '[^0-9]', '', 'g') = t.cnpj
    WHERE t.ticker = ?
      AND s.report_type IN ('BPA', 'BPP', 'DRE', 'DFC_MI', 'DFC_MD')
      AND LENGTH(s.account_code) - LENGTH(REPLACE(s.account_code, '.', '')) <= 1
    ORDER BY s.report_type, s.account_code, s.period
"""


def _extract_year(period) -> int:
    return period.year if hasattr(period, "year") else int(str(period)[:4])


def _format_value(value: float) -> str:
    abs_val = abs(int(value))
    formatted = f"{abs_val:,}".replace(",", ".")
    return f"-R${formatted}" if value < 0 else f"R${formatted}"


def _build_text(ticker: str, rows: list) -> str:
    grouped: dict = defaultdict(lambda: defaultdict(dict))
    names: dict = {}
    for period, report_type, account_code, account_name, value in rows:
        year = period.year if hasattr(period, "year") else int(str(period)[:4])
        label = _TYPE_LABELS.get(report_type, report_type)
        grouped[label][account_code][year] = value
        names[account_code] = account_name

    lines = [f"Demonstrativos CVM Oficiais — {ticker}", ""]
    for type_label, accounts in grouped.items():
        lines.append(type_label)
        for code, year_values in sorted(accounts.items()):
            parts = " | ".join(
                f"{yr}={_format_value(val)}" for yr, val in sorted(year_values.items())
            )
            lines.append(f"- {names.get(code, code)} ({code}): {parts}")
        lines.append("")
    return "\n".join(lines).strip()


def get_cvm_data(ticker: str, db_path: str) -> str:
    """Return formatted CVM statements for ticker, or '' if unavailable."""
    if not os.path.exists(db_path):
        return ""
    try:
        con = connect(db_path, read_only=True)
    except Exception:
        return ""
    try:
        row = con.execute(
            "SELECT 1 FROM ticker_map WHERE ticker = ? LIMIT 1", [ticker]
        ).fetchone()
        if row is None:
            return ""
        rows = con.execute(_QUERY, [ticker]).fetchall()
        if not rows:
            return ""
        max_year = max(_extract_year(r[0]) for r in rows)
        rows = [r for r in rows if _extract_year(r[0]) >= max_year - 2]
        return _build_text(ticker, rows)
    except Exception:
        return ""
    finally:
        con.close()
```

- [ ] **Step 4: Executar testes da source e confirmar PASS**

```bash
cd /home/paulo/Projetos/b3_llm_report && python -m pytest tests/test_report_cvm.py -v -k "get_cvm" 2>&1 | tail -10
```

Expected: 5 testes passando.

- [ ] **Step 5: Confirmar sem regressão**

```bash
cd /home/paulo/Projetos/b3_llm_report && python -m pytest tests/ -v 2>&1 | tail -5
```

Expected: todos passando.

- [ ] **Step 6: Commit**

```bash
git add src/b3_report/sources/cvm.py tests/test_report_cvm.py
git commit -m "feat: add get_cvm_data source for LLM report"
```

---

## Task 2: Atualizar `prompts.py`, `cli.py` e testes de integração

**Files:**
- Modify: `src/b3_report/prompts.py`
- Modify: `src/b3_report/cli.py`
- Modify: `tests/test_report_cvm.py` (adicionar 2 testes de prompt)

### Contexto de codebase

`src/b3_report/prompts.py` — função atual:
```python
def prepare_llm_investment_analysis_request(
    stock_info: str,
    complementary_info: str,
    analysis_date: str,
) -> str:
    return f"""...
#### Informações Complementares
{complementary_info}

### Disclaimer
..."""
```

`src/b3_report/cli.py` — trecho relevante:
```python
yfinance_report = get_yfinance_data(f"{normalized_symbol}.SA")
complementary_report = get_complementary_data(normalized_symbol)
llm_prompt = prepare_llm_investment_analysis_request(
    yfinance_report,
    complementary_report,
    analysis_date,
)
```

- [ ] **Step 1: Adicionar testes de prompt em `tests/test_report_cvm.py`**

Adicionar ao final do arquivo (após os testes existentes da source):

```python
from b3_report.prompts import prepare_llm_investment_analysis_request


def test_prompt_inclui_secao_cvm():
    prompt = prepare_llm_investment_analysis_request(
        stock_info="dados yf",
        complementary_info="dados fund",
        analysis_date="2026-03-26",
        cvm_info="Demonstrativos CVM Oficiais — PETR4\nAtivo Total...",
    )
    assert "#### Dados CVM (Demonstrativos Oficiais)" in prompt
    assert "Demonstrativos CVM Oficiais — PETR4" in prompt


def test_prompt_omite_secao_cvm():
    prompt = prepare_llm_investment_analysis_request(
        stock_info="dados yf",
        complementary_info="dados fund",
        analysis_date="2026-03-26",
        cvm_info="",
    )
    assert "#### Dados CVM" not in prompt
```

- [ ] **Step 2: Executar e confirmar FAIL**

```bash
cd /home/paulo/Projetos/b3_llm_report && python -m pytest tests/test_report_cvm.py -v -k "prompt" 2>&1 | tail -10
```

Expected: FAIL — `TypeError: prepare_llm_investment_analysis_request() got an unexpected keyword argument 'cvm_info'`

- [ ] **Step 3: Atualizar `src/b3_report/prompts.py`**

Substituir a função inteira por:

```python
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
```

- [ ] **Step 4: Executar testes de prompt e confirmar PASS**

```bash
cd /home/paulo/Projetos/b3_llm_report && python -m pytest tests/test_report_cvm.py -v -k "prompt" 2>&1 | tail -10
```

Expected: 2 testes passando.

- [ ] **Step 5: Atualizar `src/b3_report/cli.py`**

Substituir o conteúdo inteiro por:

```python
import os
from datetime import datetime

from dotenv import load_dotenv

from b3_core.config import load_config
from b3_report.llm import get_investment_analysis
from b3_report.prompts import prepare_llm_investment_analysis_request
from b3_report.sources.cvm import get_cvm_data
from b3_report.sources.fundamentus import get_complementary_data
from b3_report.sources.yfinance import get_yfinance_data


def run_report(symbol: str) -> str:
    load_dotenv()
    config = load_config()
    normalized_symbol = symbol.upper()
    analysis_date = datetime.now().strftime("%Y-%m-%d")

    yfinance_report = get_yfinance_data(f"{normalized_symbol}.SA")
    complementary_report = get_complementary_data(normalized_symbol)
    cvm_report = get_cvm_data(normalized_symbol, config.db_path)
    llm_prompt = prepare_llm_investment_analysis_request(
        yfinance_report,
        complementary_report,
        analysis_date,
        cvm_info=cvm_report,
    )
    analysis = get_investment_analysis(
        llm_prompt,
        api_key=config.openai_api_key,
        base_url=config.openai_url_base,
        model=config.openai_model_name,
    )

    os.makedirs("reports", exist_ok=True)
    report_path = os.path.join("reports", f"{normalized_symbol}.md")
    with open(report_path, "w", encoding="utf-8") as file:
        file.write(analysis)
    return analysis
```

- [ ] **Step 6: Executar todos os testes e confirmar PASS**

```bash
cd /home/paulo/Projetos/b3_llm_report && python -m pytest tests/ -v 2>&1 | tail -10
```

Expected: todos os testes passando.

- [ ] **Step 7: Commit**

```bash
git add src/b3_report/prompts.py src/b3_report/cli.py tests/test_report_cvm.py
git commit -m "feat: integrate CVM statements into LLM report prompt"
```
