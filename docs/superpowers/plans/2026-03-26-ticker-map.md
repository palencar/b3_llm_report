# Ticker Map Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir a tabela `ticker_map` (CNPJ → ticker) via API pública da B3, habilitando join entre dados CVM e o restante do pipeline.

**Architecture:** `src/b3_etl/ticker_map.py` contém toda a lógica: fetch paginado da API B3, parse/normalização de CNPJ e upsert em batch no DuckDB. CLI `build_ticker_map.py` segue o mesmo padrão de `ingest_cvm.py`. CNPJ armazenado apenas com dígitos para join consistente com `cvm_companies`.

**Tech Stack:** Python stdlib (`urllib.request`, `base64`, `json`, `re`, `time`), DuckDB (`executemany`), pytest, `unittest.mock`.

---

## Estrutura de arquivos

| Arquivo | Ação |
|---------|------|
| `src/b3_storage/schema.py` | Editar — adicionar DDL `ticker_map` + `REQUIRED_TABLES` |
| `src/b3_etl/ticker_map.py` | Criar — toda a lógica de fetch, parse e orquestração |
| `tests/test_ticker_map.py` | Criar — todos os testes |
| `build_ticker_map.py` | Criar — CLI entry point |

---

### Task 1: Schema + `parse_b3_results`

**Files:**
- Modify: `src/b3_storage/schema.py`
- Create: `src/b3_etl/ticker_map.py`
- Create: `tests/test_ticker_map.py`

- [ ] **Step 1: Escrever teste falhando**

Criar `tests/test_ticker_map.py`:

```python
"""Testes para src/b3_etl/ticker_map.py."""
import os
from unittest.mock import patch

import pytest

from b3_etl.ticker_map import parse_b3_results

# ---------------------------------------------------------------------------
# Fixtures em memória
# ---------------------------------------------------------------------------

_FAKE_RESULTS = [
    {"issuingCompany": "PETR4", "cnpj": "33000167000101", "companyName": "PETROBRAS S.A."},
    {"issuingCompany": "PETR3", "cnpj": "33000167000101", "companyName": "PETROBRAS S.A."},
    {"issuingCompany": "",      "cnpj": "99999999000100", "companyName": "SEM TICKER"},
    {"issuingCompany": "ITUB4", "cnpj": "",               "companyName": "SEM CNPJ"},
    {"issuingCompany": "VALE3", "cnpj": "33.592.510/0001-03", "companyName": "VALE S.A."},
]

_FAKE_PAGE_1 = {
    "totalPages": 2,
    "results": [
        {"issuingCompany": "PETR4", "cnpj": "33000167000101", "companyName": "PETROBRAS S.A."},
        {"issuingCompany": "PETR3", "cnpj": "33000167000101", "companyName": "PETROBRAS S.A."},
        {"issuingCompany": "",      "cnpj": "99999999000100", "companyName": "SEM TICKER"},
        {"issuingCompany": "ITUB4", "cnpj": "",               "companyName": "SEM CNPJ"},
    ],
}

_FAKE_PAGE_2 = {
    "totalPages": 2,
    "results": [
        {"issuingCompany": "VALE3", "cnpj": "33592510000103", "companyName": "VALE S.A."},
    ],
}


def _fake_fetch(page: int, page_size: int = 120, timeout: int = 30) -> dict:
    return _FAKE_PAGE_1 if page == 1 else _FAKE_PAGE_2


def _init_db(db_path: str) -> None:
    from b3_storage.schema import SCHEMA_SQL
    from b3_storage.db import connect
    con = connect(db_path, read_only=False)
    for stmt in SCHEMA_SQL.split(";"):
        stmt = stmt.strip()
        if stmt:
            con.execute(stmt)
    con.close()


def _make_config(tmp_path: str):
    from b3_core.config import load_config
    config = load_config()
    db_path = os.path.join(tmp_path, "test.duckdb")
    _init_db(db_path)
    return config.__class__(
        **{**config.__dict__, "db_path": db_path}
    )


# ---------------------------------------------------------------------------
# Task 1: parse_b3_results
# ---------------------------------------------------------------------------

def test_parse_b3_results():
    result = parse_b3_results(_FAKE_RESULTS)
    # PETR4, PETR3, VALE3 válidos; SEM TICKER (ticker vazio) e SEM CNPJ (cnpj vazio) ignorados
    assert len(result) == 3
    tickers = {r["ticker"] for r in result}
    assert "PETR4" in tickers
    assert "PETR3" in tickers
    assert "VALE3" in tickers
    # CNPJ normalizado: apenas dígitos
    petr4 = next(r for r in result if r["ticker"] == "PETR4")
    assert petr4["cnpj"] == "33000167000101"
    assert petr4["name"] == "PETROBRAS S.A."
    # CNPJ com pontuação também é normalizado
    vale = next(r for r in result if r["ticker"] == "VALE3")
    assert vale["cnpj"] == "33592510000103"
```

- [ ] **Step 2: Executar — deve falhar**

```bash
cd /home/paulo/Projetos/b3_llm_report && python -m pytest tests/test_ticker_map.py::test_parse_b3_results -v
```

Esperado: `ImportError: cannot import name 'parse_b3_results' from 'b3_etl.ticker_map'`

- [ ] **Step 3: Atualizar `src/b3_storage/schema.py`**

Adicionar `"ticker_map"` a `REQUIRED_TABLES` e o DDL a `SCHEMA_SQL`. Ler o arquivo antes de editar para não sobrescrever o conteúdo existente.

`REQUIRED_TABLES` deve ficar:

```python
REQUIRED_TABLES = [
    "companies",
    "fundamentals",
    "prices",
    "ratios",
    "raw_files",
    "cvm_companies",
    "cvm_statements",
    "ticker_map",
]
```

Adicionar ao final de `SCHEMA_SQL` (antes do `.strip()`):

```sql
-- ticker_map
CREATE TABLE IF NOT EXISTS ticker_map (
    cnpj       TEXT,
    ticker     TEXT,
    name       TEXT,
    updated_at TIMESTAMP,
    PRIMARY KEY (cnpj, ticker)
);
```

- [ ] **Step 4: Criar `src/b3_etl/ticker_map.py` com `parse_b3_results`**

```python
"""Mapeamento CNPJ → ticker via API pública da B3."""
import base64
import json
import os
import re
import time
import urllib.request
from datetime import datetime, timezone

from b3_core.config import Config
from b3_core.log import log_info, log_error
from b3_storage.db import connect, missing_tables

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_B3_API_URL = (
    "https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy"
    "/CompanyCall/GetInitialCompanies/{params}"
)

_CNPJ_RE = re.compile(r"\D")

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_b3_results(results: list[dict]) -> list[dict]:
    """Parse B3 API result list. Returns list of {cnpj, ticker, name}.

    Filters records with empty issuingCompany or cnpj.
    Normalizes CNPJ to digits only.
    """
    out = []
    for r in results:
        ticker = r.get("issuingCompany", "").strip()
        raw_cnpj = r.get("cnpj", "").strip()
        if not ticker or not raw_cnpj:
            continue
        cnpj = _CNPJ_RE.sub("", raw_cnpj)
        if not cnpj:
            continue
        out.append({
            "ticker": ticker,
            "cnpj": cnpj,
            "name": r.get("companyName", "").strip(),
        })
    return out
```

- [ ] **Step 5: Executar — deve passar**

```bash
cd /home/paulo/Projetos/b3_llm_report && python -m pytest tests/test_ticker_map.py::test_parse_b3_results -v
```

Esperado: `1 passed`

- [ ] **Step 6: Commit**

```bash
cd /home/paulo/Projetos/b3_llm_report && git add src/b3_storage/schema.py src/b3_etl/ticker_map.py tests/test_ticker_map.py && git commit -m "feat: schema ticker_map + parse_b3_results"
```

---

### Task 2: `fetch_b3_page` + `run_build_ticker_map`

**Files:**
- Modify: `src/b3_etl/ticker_map.py`
- Modify: `tests/test_ticker_map.py`

- [ ] **Step 1: Escrever testes falhando**

Adicionar ao final de `tests/test_ticker_map.py`:

```python
from b3_etl.ticker_map import run_build_ticker_map
from b3_storage.db import connect


def test_run_build_ticker_map_popula_tabela(tmp_path):
    """run_build_ticker_map deve gravar ticker_map com registros corretos."""
    config = _make_config(str(tmp_path))
    with patch("b3_etl.ticker_map.fetch_b3_page", side_effect=_fake_fetch):
        rc = run_build_ticker_map(config=config)
    assert rc == 0

    con = connect(config.db_path, read_only=True)
    count = con.execute("SELECT COUNT(*) FROM ticker_map").fetchone()[0]
    tickers = {r[0] for r in con.execute("SELECT ticker FROM ticker_map").fetchall()}
    con.close()

    # PETR4, PETR3 (página 1) + VALE3 (página 2) = 3; SEM TICKER e SEM CNPJ ignorados
    assert count == 3
    assert "PETR4" in tickers
    assert "PETR3" in tickers
    assert "VALE3" in tickers


def test_run_build_ticker_map_falha_rede(tmp_path):
    """OSError na página 2 → rc=0, dados da página 1 gravados."""
    config = _make_config(str(tmp_path))

    def _fake_page2_fails(page: int, page_size: int = 120, timeout: int = 30) -> dict:
        if page == 1:
            return _FAKE_PAGE_1  # totalPages=2
        raise OSError("timeout")

    with patch("b3_etl.ticker_map.fetch_b3_page", side_effect=_fake_page2_fails):
        rc = run_build_ticker_map(config=config)
    assert rc == 0

    con = connect(config.db_path, read_only=True)
    count = con.execute("SELECT COUNT(*) FROM ticker_map").fetchone()[0]
    tickers = {r[0] for r in con.execute("SELECT ticker FROM ticker_map").fetchall()}
    con.close()

    # Apenas PETR4 e PETR3 (página 1); VALE3 não gravado (página 2 falhou)
    assert count == 2
    assert "PETR4" in tickers
    assert "PETR3" in tickers


def test_run_build_ticker_map_idempotente(tmp_path):
    """Segunda execução produz o mesmo resultado sem duplicatas."""
    config = _make_config(str(tmp_path))
    with patch("b3_etl.ticker_map.fetch_b3_page", side_effect=_fake_fetch):
        run_build_ticker_map(config=config)
        run_build_ticker_map(config=config)

    con = connect(config.db_path, read_only=True)
    count = con.execute("SELECT COUNT(*) FROM ticker_map").fetchone()[0]
    con.close()
    assert count == 3  # mesmo resultado, sem duplicatas
```

- [ ] **Step 2: Executar — devem falhar**

```bash
cd /home/paulo/Projetos/b3_llm_report && python -m pytest tests/test_ticker_map.py::test_run_build_ticker_map_popula_tabela tests/test_ticker_map.py::test_run_build_ticker_map_falha_rede tests/test_ticker_map.py::test_run_build_ticker_map_idempotente -v
```

Esperado: `ImportError: cannot import name 'run_build_ticker_map'`

- [ ] **Step 3: Adicionar `fetch_b3_page` e `run_build_ticker_map` a `src/b3_etl/ticker_map.py`**

Adicionar após `parse_b3_results`:

```python
def fetch_b3_page(page: int, page_size: int = 120, timeout: int = 30) -> dict:
    """Fetch one page from B3 listed companies API.

    Returns dict with {results: [...], totalPages: N}.
    Raises OSError on network failure.
    """
    params = json.dumps(
        {"language": "pt-br", "pageNumber": page, "pageSize": page_size},
        separators=(",", ":"),
    )
    encoded = base64.b64encode(params.encode()).decode()
    url = _B3_API_URL.format(params=encoded)
    req = urllib.request.Request(url, headers={"User-Agent": "b3-llm-report/etl"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run_build_ticker_map(config: Config, skip_db: bool = False) -> int:
    """Fetch B3 listed companies API and upsert ticker_map.

    Returns rc=0 always. Errors are logged and non-fatal.
    """
    log_info("etl_ticker_map_start")
    t0 = time.time()

    con = None
    if not skip_db:
        con = connect(config.db_path, read_only=False)
        missing = missing_tables(con)
        if missing:
            log_error("etl_ticker_map_start", error=f"tabelas ausentes: {missing}")
            con.close()
            return 1

    all_records: list[dict] = []
    total_pages = 1
    page = 1

    while page <= total_pages:
        try:
            data = fetch_b3_page(page)
            total_pages = data.get("totalPages", 1)
            records = parse_b3_results(data.get("results", []))
            all_records.extend(records)
            log_info("etl_ticker_map_page", page=page, total_pages=total_pages, rows=len(records))
        except OSError as exc:
            log_error("etl_ticker_map_page", page=page, error=str(exc))
        page += 1

    if con and all_records:
        fetched_at = datetime.now(timezone.utc).replace(tzinfo=None)
        try:
            con.execute("BEGIN")
            con.executemany(
                "INSERT OR REPLACE INTO ticker_map (cnpj, ticker, name, updated_at)"
                " VALUES (?, ?, ?, ?)",
                [(r["cnpj"], r["ticker"], r["name"], fetched_at) for r in all_records],
            )
            con.execute(
                "INSERT OR REPLACE INTO raw_files"
                " (source, path, fetched_at, checksum, size_bytes) VALUES (?, ?, ?, ?, ?)",
                ["b3_ticker_map", "b3_api_v1", fetched_at, "", 0],
            )
            con.execute("COMMIT")
        except Exception as exc:
            con.execute("ROLLBACK")
            log_error("etl_ticker_map_done", error=str(exc))

    if con:
        con.close()

    duration_ms = int((time.time() - t0) * 1000)
    log_info("etl_ticker_map_done", rows_inserted=len(all_records), duration_ms=duration_ms)
    return 0
```

- [ ] **Step 4: Executar os 3 novos testes — devem passar**

```bash
cd /home/paulo/Projetos/b3_llm_report && python -m pytest tests/test_ticker_map.py::test_run_build_ticker_map_popula_tabela tests/test_ticker_map.py::test_run_build_ticker_map_falha_rede tests/test_ticker_map.py::test_run_build_ticker_map_idempotente -v
```

Esperado: `3 passed`

- [ ] **Step 5: Executar suíte completa**

```bash
cd /home/paulo/Projetos/b3_llm_report && python -m pytest tests/ -q
```

Esperado: todos os testes passando

- [ ] **Step 6: Commit**

```bash
cd /home/paulo/Projetos/b3_llm_report && git add src/b3_etl/ticker_map.py tests/test_ticker_map.py && git commit -m "feat: fetch_b3_page e run_build_ticker_map com paginação e upsert"
```

---

### Task 3: CLI `build_ticker_map.py`

**Files:**
- Create: `build_ticker_map.py`

- [ ] **Step 1: Criar `build_ticker_map.py`**

```python
import argparse
import os
import sys

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from b3_core.config import load_config
from b3_etl.ticker_map import run_build_ticker_map


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Constrói mapeamento CNPJ→ticker via API da B3."
    )
    parser.add_argument(
        "--skip-db",
        action="store_true",
        help="Não gravar no DuckDB (apenas parseia e loga).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    config = load_config()
    return run_build_ticker_map(config=config, skip_db=args.skip_db)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Verificar sintaxe**

```bash
cd /home/paulo/Projetos/b3_llm_report && python -m py_compile build_ticker_map.py src/b3_etl/ticker_map.py
```

Esperado: sem saída (silencioso = sucesso)

- [ ] **Step 3: Executar suíte completa**

```bash
cd /home/paulo/Projetos/b3_llm_report && python -m pytest tests/ -v
```

Esperado: todos os testes passando

- [ ] **Step 4: Verificar que `init_db.py` cria a nova tabela**

```bash
cd /home/paulo/Projetos/b3_llm_report && python init_db.py && python -c "
import sys; sys.path.insert(0, 'src')
import duckdb
con = duckdb.connect('data/duckdb/b3_fundamentals.duckdb', read_only=True)
tables = con.execute(\"SELECT table_name FROM information_schema.tables WHERE table_name = 'ticker_map'\").fetchall()
print('Tabela ticker_map:', tables)
con.close()
"
```

Esperado: `Tabela ticker_map: [('ticker_map',)]`

- [ ] **Step 5: Commit**

```bash
cd /home/paulo/Projetos/b3_llm_report && git add build_ticker_map.py && git commit -m "feat: CLI build_ticker_map.py para mapeamento CNPJ→ticker via API B3"
```

---

## Comandos para teste manual (após implementação)

```bash
# 1. Recriar DB com nova tabela (idempotente)
python init_db.py

# 2. Popular ticker_map via API B3
python build_ticker_map.py

# 3. Verificar mapeamento
python -c "
import sys; sys.path.insert(0, 'src')
import duckdb
con = duckdb.connect('data/duckdb/b3_fundamentals.duckdb', read_only=True)
rows = con.execute(\"SELECT cnpj, ticker, name FROM ticker_map WHERE ticker IN ('PETR4','PETR3','VALE3') LIMIT 10\").fetchall()
for r in rows: print(r)
con.close()
"

# 4. Join ticker_map → cvm_statements (requer cvm ingerido)
python -c "
import sys; sys.path.insert(0, 'src')
import duckdb
con = duckdb.connect('data/duckdb/b3_fundamentals.duckdb', read_only=True)
rows = con.execute('''
    SELECT s.report_type, s.account_code, s.account_name, s.value
    FROM cvm_statements s
    JOIN cvm_companies c ON c.cnpj = s.cnpj
    JOIN ticker_map t    ON regexp_replace(c.cnpj, '[^0-9]', \\'\\', \\'g\\') = t.cnpj
    WHERE t.ticker = \\'PETR4\\'
      AND s.period = \\'2024-12-31\\'
    LIMIT 5
''').fetchall()
for r in rows: print(r)
con.close()
"
```
