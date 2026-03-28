# Design — Otimização do Ingest CVM e Fix de Paginação ticker_map

**Data:** 2026-03-27
**Escopo:** Três correções independentes em `src/b3_etl/cvm.py` e `src/b3_etl/ticker_map.py`

---

## Problema

### 1. `executemany` row-by-row é lento

`run_ingest_cvm` chama `con.executemany(INSERT OR REPLACE, list_of_tuples)` com 620k tuplas de uma vez. O DuckDB itera cada tupla via Python, verificando a PK a cada row. Resultado: ~30s por lote de 10k rows → ~30 minutos para o DFP 2024.

### 2. Duplicatas _con/_ind sem preferência definida

O ZIP DFP contém dois CSVs por tipo de demonstrativo: `_con` (consolidado) e `_ind` (individual). Empresas com ambos produzem rows idênticas em `(cnpj, period, report_type, account_code)`. Como `_con` vem antes de `_ind` na ordem alfabética, o individual sobrescreve o consolidado no `INSERT OR REPLACE` — o oposto do correto.

### 3. Paginação ticker_map quebrada

`run_build_ticker_map` usa `data.get("totalPages", 1)`. A API B3 retorna `totalPages` aninhado em `data["page"]["totalPages"]`. O loop sempre termina na página 1 → apenas 120 das 3.366 empresas são carregadas.

---

## Solução

### `parse_statements` — dedup com preferência _con

Substituir a lista acumulada por um dict keyed em `(cnpj, period, report_type, account_code)`. CSVs ordenados de modo que `_ind` seja processado antes de `_con` (sort key: `1 if "_con" in name.lower() else 0`), garantindo que o consolidado sobrescreva o individual.

Interface pública mantida: retorna `list[dict]` com as mesmas chaves de antes.

```python
names = sorted(zf.namelist(), key=lambda n: (1 if "_con" in n.lower() else 0, n))
seen: dict = {}
for name in names:
    ...
    key = (cnpj, period, report_type, account_code)
    seen[key] = {row_data}
return list(seen.values())
```

### `run_ingest_cvm` — bulk insert via pandas

Substituir o `executemany` por:

```python
import pandas as pd

df = pd.DataFrame(records)
df["fetched_at"] = fetched_at
con.execute("BEGIN")
con.register("_staging", df)
con.execute("""
    INSERT OR REPLACE INTO cvm_statements
        (cnpj, period, report_type, account_code, account_name,
         value, currency, source, fetched_at)
    SELECT cnpj, period::DATE, report_type, account_code, account_name,
           value, currency, source, fetched_at
    FROM _staging
""")
con.unregister("_staging")
con.execute("COMMIT")
```

DuckDB processa o DataFrame em modo colunar — esperado ~1-5s para 600k rows.

Mesmo padrão aplicado ao bloco ITR.

### `run_build_ticker_map` — fix de paginação

```python
# antes
total_pages = data.get("totalPages", 1)
# depois
total_pages = data.get("page", {}).get("totalPages", 1)
```

### `requirements-etl.txt`

Adicionar `pandas>=2.0,<3.0`.

---

## Arquivos modificados

| Arquivo | Mudança |
|---------|---------|
| `src/b3_etl/cvm.py` | `parse_statements`: dict + sort para dedup _con/_ind |
| `src/b3_etl/cvm.py` | `run_ingest_cvm`: substituir `executemany` por pandas bulk insert (DFP e ITR) |
| `src/b3_etl/ticker_map.py` | `run_build_ticker_map`: fix acesso a `data["page"]["totalPages"]` |
| `requirements-etl.txt` | Adicionar `pandas>=2.0,<3.0` |
| `tests/test_cvm.py` | Adicionar teste de dedup _con/_ind |
| `tests/test_ticker_map.py` | Atualizar fixtures para nova estrutura da API; adicionar teste de paginação |

---

## Testes

### Novos testes em `tests/test_cvm.py`

**`test_parse_statements_prefere_con_sobre_ind`**
- ZIP com dois CSVs: `dfp_cia_aberta_BPA_ind_2024.csv` (valor 50k) e `dfp_cia_aberta_BPA_con_2024.csv` (valor 100k) para o mesmo (cnpj, period, account_code)
- `parse_statements` retorna 1 row com value=100_000_000 (consolidado prevalece)

### Testes existentes em `tests/test_cvm.py`

`test_run_ingest_cvm_popula_tabelas` — fixture usa arquivo sem `_con`/`_ind`; dedup não afeta contagem → passa sem mudança.

`test_parse_statements_dfp` / `test_parse_statements_filtra_penultimo` — fixture sem duplicatas → passam sem mudança.

### Atualização em `tests/test_ticker_map.py`

Fixtures `_FAKE_PAGE_1` e `_FAKE_PAGE_2` atualizadas para nova estrutura da API B3:

```python
_FAKE_PAGE_1 = {
    "page": {"pageNumber": 1, "pageSize": 4, "totalRecords": 5, "totalPages": 2},
    "results": [...],
}
```

**`test_paginacao_usa_page_totalPages`** — mock retorna `{"page": {"totalPages": 2}, "results": [...]}` → confirma que o loop busca página 2.

---

## Critérios de aceitação

1. `parse_statements` com ZIP contendo `_con` e `_ind` para o mesmo ticker/conta retorna um único row com o valor do `_con`
2. `run_ingest_cvm` completa o DFP 2024 (620k rows) em menos de 60s
3. `run_build_ticker_map` busca todas as páginas (≥ 2 páginas no mock)
4. `pytest tests/test_cvm.py tests/test_ticker_map.py -v` — todos passam
