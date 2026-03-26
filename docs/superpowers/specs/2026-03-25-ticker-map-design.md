# Design — Mapeamento CNPJ → Ticker (B3 API)

**Data:** 2026-03-25
**Escopo:** Construção da tabela `ticker_map` via API pública da B3, habilitando join entre dados CVM (por CNPJ) e dados BRAPI/Fundamentus (por ticker)

---

## Contexto

Os dados CVM (`cvm_statements`, `cvm_companies`) são indexados por CNPJ. O restante do pipeline (BRAPI, Fundamentus, MCP, relatório LLM) opera por ticker B3. Sem o mapeamento CNPJ → ticker, os dados CVM ficam inacessíveis por ticker.

A B3 expõe uma API JSON pública paginada que retorna, por empresa listada: ticker (`issuingCompany`), CNPJ (`cnpj`), código CVM (`codeCVM`) e nome (`companyName`). Essa API elimina a necessidade de arquivos manuais ou scraping.

**URL da API:**
```
https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/CompanyCall/GetInitialCompanies/{base64_params}
```

`base64_params` é o JSON `{"language":"pt-br","pageNumber":N,"pageSize":120}` codificado em base64.

Retorna ~3.365 empresas em ~28 páginas (pageSize=120).

---

## Arquitetura

### Novos arquivos

| Arquivo | Ação |
|---------|------|
| `src/b3_storage/schema.py` | Editar — adicionar DDL de `ticker_map` e incluir em `REQUIRED_TABLES` |
| `src/b3_etl/ticker_map.py` | Criar — fetch da API B3, parse e orquestração |
| `build_ticker_map.py` | Criar — CLI entry point |
| `tests/test_ticker_map.py` | Criar — testes unitários |

### Nova tabela DuckDB

```sql
CREATE TABLE IF NOT EXISTS ticker_map (
    cnpj       TEXT,
    ticker     TEXT,
    name       TEXT,
    updated_at TIMESTAMP,
    PRIMARY KEY (cnpj, ticker)
);
```

- `cnpj` armazenado apenas com dígitos (sem pontuação) para join consistente
- Múltiplos tickers por CNPJ são permitidos (ON e PN da mesma empresa)
- Adicionada a `REQUIRED_TABLES` em `schema.py`

---

## CLI

```bash
# Fetch API B3 → upsert ticker_map
python build_ticker_map.py

# Só parseia, não grava no DuckDB
python build_ticker_map.py --skip-db
```

Sem flags obrigatórias — a API é sempre a fonte, sem arquivo manual.

---

## Módulo `src/b3_etl/ticker_map.py`

Três funções públicas:

```python
def fetch_b3_page(page: int, page_size: int = 120, timeout: int = 30) -> dict
    # GET API B3 com params base64-encoded (json → base64 → URL)
    # Retorna dict com {results: [...], totalPages: N}
    # Levanta OSError em falha de rede

def parse_b3_results(results: list[dict]) -> list[dict]
    # Filtra linhas com issuingCompany ou cnpj vazios
    # Normaliza CNPJ: re.sub(r"\D", "", cnpj) → apenas dígitos
    # Mapeia: issuingCompany → ticker, cnpj → cnpj, companyName → name
    # Retorna lista de {cnpj, ticker, name}

def run_build_ticker_map(config: Config, skip_db: bool = False) -> int
    # Pagina a API: fetch página 1, obtém totalPages, itera restantes
    # Batch upsert em ticker_map via executemany INSERT OR REPLACE (BEGIN/COMMIT)
    # Loga rows_inserted e páginas processadas
    # Retorna rc=0 sempre; erros de página logados e não-fatais
```

### Normalização de CNPJ

O CNPJ retornado pela API vem sem formatação (`46639922000144`). O campo `cvm_companies.cnpj` usa formatação com pontuação (`46.639.922/0001-44`). A normalização é feita no momento do parse:

```python
_CNPJ_RE = re.compile(r"\D")
cnpj_digits = _CNPJ_RE.sub("", raw_cnpj)
```

O join com `cvm_companies` usa a mesma normalização via SQL:

```sql
SELECT s.*
FROM cvm_statements s
JOIN cvm_companies c ON c.cnpj = s.cnpj
JOIN ticker_map t    ON regexp_replace(c.cnpj, '[^0-9]', '', 'g') = t.cnpj
WHERE t.ticker = 'PETR4'
  AND s.period >= '2024-01-01';
```

---

## Fluxo de execução

```
run_build_ticker_map(config, skip_db)
│
├── fetch_b3_page(page=1) → totalPages
│
├── para cada página 1..totalPages:
│   ├── fetch_b3_page(page=N)  [OSError → log_error, continua]
│   └── parse_b3_results(results) → records
│
└── [se não skip_db] batch upsert ticker_map (BEGIN/COMMIT)
    └── registra em raw_files com source='b3_ticker_map'
```

---

## Tratamento de erros

| Situação | Comportamento |
|---|---|
| Falha de rede numa página | `log_error("etl_ticker_map_page", ...)` + continua próxima página |
| CNPJ ou ticker vazios | linha ignorada silenciosamente |
| Falha de transação DuckDB | ROLLBACK + `log_error` + rc=0 |
| `rc` final | sempre 0 |

---

## Logs estruturados

```json
{"level": "info", "job": "etl_ticker_map_start"}
{"level": "info", "job": "etl_ticker_map_page", "page": 1, "total_pages": 28, "rows": 120}
{"level": "info", "job": "etl_ticker_map_done", "rows_inserted": 3180, "duration_ms": 4200}
```

---

## Testes

Fixtures em memória (sem rede), seguindo padrão de `test_cvm.py`:

```python
_FAKE_PAGE_1 = {
    "totalPages": 2,
    "results": [
        {"issuingCompany": "PETR4", "cnpj": "33000167000101", "companyName": "PETROBRAS S.A."},
        {"issuingCompany": "PETR3", "cnpj": "33000167000101", "companyName": "PETROBRAS S.A."},
        {"issuingCompany": "",      "cnpj": "99999999000100", "companyName": "SEM TICKER"},
        {"issuingCompany": "ITUB4", "cnpj": "",               "companyName": "SEM CNPJ"},
    ]
}
_FAKE_PAGE_2 = {
    "totalPages": 2,
    "results": [
        {"issuingCompany": "VALE3", "cnpj": "33592510000103", "companyName": "VALE S.A."},
    ]
}
```

| Teste | O que verifica |
|-------|----------------|
| `test_parse_b3_results` | CNPJ normalizado (só dígitos), ticker extraído, linhas sem ticker ou cnpj ignoradas |
| `test_run_build_ticker_map_popula_tabela` | DuckDB tmp: ticker_map populada com registros corretos após run com mock de `fetch_b3_page` |
| `test_run_build_ticker_map_falha_rede` | OSError numa página → rc=0, páginas restantes processadas |
| `test_run_build_ticker_map_idempotente` | Segunda execução: mesmo resultado sem duplicatas (upsert) |

---

## Dependências

Nenhuma nova. `urllib.request`, `base64`, `json`, `re` são stdlib. `duckdb` já em `requirements-etl.txt`.

---

## O que não muda

- Schema das tabelas existentes
- Interface de `run_ingest_cvm` e `run_ingest`
- `requirements-etl.txt`

---

## Critérios de aceitação

1. `python init_db.py` cria `ticker_map` em banco novo ou existente (idempotente)
2. `python build_ticker_map.py` popula `ticker_map` com tickers e CNPJs normalizados
3. Segunda execução consecutiva é idempotente (mesmo resultado, sem duplicatas)
4. Falha de rede em página individual não interrompe o processo (rc=0)
5. `pytest tests/test_ticker_map.py -v` — todos os testes passam sem acesso à rede
6. Join `ticker_map → cvm_statements` retorna dados corretos para PETR4
