# CVM Ingest Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corrigir três bugs independentes: dedup _con/_ind em `parse_statements`, bulk insert via pandas em `run_ingest_cvm`, e fix de paginação em `run_build_ticker_map`.

**Architecture:** `parse_statements` troca lista por dict keyed em PK, processando `_con` por último para que sobrescreva `_ind`. `run_ingest_cvm` registra um DataFrame pandas no DuckDB e faz INSERT via SQL colunar. `run_build_ticker_map` lê `totalPages` de `data["page"]["totalPages"]` em vez de `data["totalPages"]`.

**Tech Stack:** Python 3.13, DuckDB 0.10.2, pandas ≥2.0.

---

## Estrutura de arquivos

| Arquivo | Ação |
|---------|------|
| `src/b3_etl/cvm.py` | Modificar — `parse_statements` (dedup) + `run_ingest_cvm` (pandas) |
| `src/b3_etl/ticker_map.py` | Modificar — fix paginação (1 linha) |
| `requirements-etl.txt` | Modificar — adicionar `pandas>=2.0,<3.0` |
| `tests/test_cvm.py` | Modificar — adicionar teste de dedup _con/_ind |
| `tests/test_ticker_map.py` | Modificar — atualizar fixtures + adicionar teste de paginação |

---

## Task 1: `parse_statements` — dedup com preferência _con

**Files:**
- Modify: `src/b3_etl/cvm.py:51-99`
- Test: `tests/test_cvm.py`

### Contexto

O ZIP DFP contém `dfp_cia_aberta_BPA_con_2024.csv` e `dfp_cia_aberta_BPA_ind_2024.csv`. Hoje o código acumula todos os rows numa lista e o `_ind` (vem depois na ordem alfa) sobrescreve o `_con` no INSERT. A correção usa um dict keyed em `(cnpj, period, report_type, account_code)` e processa `_ind` antes de `_con` na ordenação — garantindo que `_con` seja o valor final.

- [ ] **Step 1: Adicionar o teste de dedup em `tests/test_cvm.py`**

Adicionar logo após `test_parse_statements_filtra_penultimo` (linha ~135):

```python
_DFP_BPA_IND_CSV = (
    "CNPJ_CIA;DT_REFER;ORDEM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;MOEDA;ESCALA_MOEDA\n"
    "33.000.167/0001-01;2024-12-31;ÚLTIMO;1;Ativo Total;50000;REAL;MIL\n"
)

_DFP_BPA_CON_CSV = (
    "CNPJ_CIA;DT_REFER;ORDEM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;MOEDA;ESCALA_MOEDA\n"
    "33.000.167/0001-01;2024-12-31;ÚLTIMO;1;Ativo Total;100000;REAL;MIL\n"
)


def test_parse_statements_prefere_con_sobre_ind(tmp_path):
    """Con (consolidado) deve prevalecer sobre ind (individual) para mesma PK."""
    path = os.path.join(str(tmp_path), "dfp_con_ind.zip")
    with open(path, "wb") as f:
        f.write(_zip_bytes({
            "dfp_cia_aberta_BPA_ind_2024.csv": _DFP_BPA_IND_CSV,
            "dfp_cia_aberta_BPA_con_2024.csv": _DFP_BPA_CON_CSV,
        }))
    result = parse_statements(path, "cvm_dfp")
    # Deve haver apenas 1 row (dedup por PK), com o valor do _con (100_000_000)
    assert len(result) == 1
    assert result[0]["value"] == 100_000_000.0
```

- [ ] **Step 2: Rodar e confirmar FAIL**

```bash
cd /home/paulo/Projetos/b3_llm_report && python -m pytest tests/test_cvm.py::test_parse_statements_prefere_con_sobre_ind -v 2>&1 | tail -10
```

Expected: FAIL — `AssertionError: assert 2 == 1` (atualmente retorna 2 rows porque não deduplica).

- [ ] **Step 3: Substituir `parse_statements` em `src/b3_etl/cvm.py`**

Substituir as linhas 51–99 (função inteira) por:

```python
def parse_statements(zip_path: str, source: str) -> list[dict]:
    """Parse DFP/ITR ZIP. Returns deduplicated list of statement records.

    Filters ORDEM_EXERC == 'ÚLTIMO'. Normalizes VL_CONTA by ESCALA_MOEDA.
    When both _con and _ind CSVs exist for the same account, _con (consolidated)
    takes precedence. period is returned as datetime.date.
    """
    seen: dict = {}
    with zipfile.ZipFile(zip_path) as zf:
        # Process _ind before _con so consolidated overwrites individual
        names = sorted(
            (n for n in zf.namelist() if n.lower().endswith(".csv")),
            key=lambda n: (1 if "_con" in n.lower() else 0, n),
        )
        for name in names:
            report_type = _extract_report_type(name)
            if report_type is None:
                continue
            with zf.open(name) as raw:
                reader = csv.DictReader(
                    io.TextIOWrapper(raw, encoding="latin-1"), delimiter=";"
                )
                for row in reader:
                    if row.get("ORDEM_EXERC", "").strip() != "ÚLTIMO":
                        continue
                    cnpj = row.get("CNPJ_CIA", "").strip()
                    dt_refer = row.get("DT_REFER", "").strip()
                    cd_conta = row.get("CD_CONTA", "").strip()
                    ds_conta = row.get("DS_CONTA", "").strip()
                    vl_conta = row.get("VL_CONTA", "").strip()
                    moeda = row.get("MOEDA", "REAL").strip()
                    escala = row.get("ESCALA_MOEDA", "UNIDADE").strip()
                    if not cnpj or not dt_refer or not vl_conta:
                        continue
                    try:
                        period = datetime.strptime(dt_refer, "%Y-%m-%d").date()
                    except ValueError:
                        continue
                    try:
                        value = float(vl_conta.replace(",", ".")) * _SCALE.get(escala, 1)
                    except ValueError:
                        continue
                    key = (cnpj, period, report_type, cd_conta)
                    seen[key] = {
                        "cnpj": cnpj,
                        "period": period,
                        "report_type": report_type,
                        "account_code": cd_conta,
                        "account_name": ds_conta,
                        "value": value,
                        "currency": moeda,
                        "source": source,
                    }
    return list(seen.values())
```

- [ ] **Step 4: Rodar todos os testes de cvm e confirmar PASS**

```bash
cd /home/paulo/Projetos/b3_llm_report && python -m pytest tests/test_cvm.py -v 2>&1 | tail -15
```

Expected: todos os testes passando (incluindo os existentes que não usam _con/_ind).

- [ ] **Step 5: Commit**

```bash
git add src/b3_etl/cvm.py tests/test_cvm.py
git commit -m "$(cat <<'EOF'
fix: parse_statements dedup prefer _con over _ind

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `run_ingest_cvm` — pandas bulk insert

**Files:**
- Modify: `src/b3_etl/cvm.py:1-10` (import) e `src/b3_etl/cvm.py:231-305` (DFP e ITR blocks)
- Modify: `requirements-etl.txt`

### Contexto

O `executemany` itera row-by-row em Python (~30s por 10k rows). Substituímos por:
1. Converter `list[dict]` → `pd.DataFrame`
2. `con.register("_staging", df)` — expõe o DataFrame como view SQL no DuckDB
3. `INSERT OR REPLACE INTO cvm_statements SELECT ... FROM _staging` — DuckDB processa em modo colunar (~1-5s para 600k rows)
4. `con.unregister("_staging")` — limpa a view

O bloco ITR usa a mesma lógica, mas só insere rows que não existem no DFP (`to_insert`).

Testes existentes não mudam — a interface de `run_ingest_cvm` é idêntica.

- [ ] **Step 1: Adicionar `pandas` ao `requirements-etl.txt`**

Substituir o conteúdo de `requirements-etl.txt` por:

```
duckdb==0.10.2
pandas>=2.0,<3.0
```

- [ ] **Step 2: Adicionar `import pandas as pd` no topo de `src/b3_etl/cvm.py`**

Após a linha `import zipfile` (linha 9), adicionar:

```python
import pandas as pd
```

- [ ] **Step 3: Substituir o bloco DFP em `run_ingest_cvm` (linhas 231–255)**

Substituir:

```python
        if con and dfp_records:
            try:
                con.execute("BEGIN")
                con.executemany(
                    "INSERT OR REPLACE INTO cvm_statements"
                    " (cnpj, period, report_type, account_code, account_name,"
                    "  value, currency, source, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (r["cnpj"], r["period"], r["report_type"], r["account_code"],
                         r["account_name"], r["value"], r["currency"], r["source"], fetched_at)
                        for r in dfp_records
                    ],
                )
                con.execute(
                    "INSERT OR REPLACE INTO raw_files"
                    " (source, path, fetched_at, checksum, size_bytes) VALUES (?, ?, ?, ?, ?)",
                    ["cvm_dfp", dfp_path, fetched_at, checksum, size_bytes],
                )
                con.execute("COMMIT")
                rows_statements += len(dfp_records)
            except Exception as exc:
                con.execute("ROLLBACK")
                log_error("etl_cvm_zip", type="dfp", error=str(exc))
```

Por:

```python
        if con and dfp_records:
            try:
                df = pd.DataFrame(dfp_records)
                df["fetched_at"] = fetched_at
                con.execute("BEGIN")
                con.register("_staging", df)
                con.execute(
                    "INSERT OR REPLACE INTO cvm_statements"
                    " (cnpj, period, report_type, account_code, account_name,"
                    "  value, currency, source, fetched_at)"
                    " SELECT cnpj, period::DATE, report_type, account_code, account_name,"
                    "        value, currency, source, fetched_at"
                    " FROM _staging"
                )
                con.unregister("_staging")
                con.execute(
                    "INSERT OR REPLACE INTO raw_files"
                    " (source, path, fetched_at, checksum, size_bytes) VALUES (?, ?, ?, ?, ?)",
                    ["cvm_dfp", dfp_path, fetched_at, checksum, size_bytes],
                )
                con.execute("COMMIT")
                rows_statements += len(dfp_records)
            except Exception as exc:
                con.execute("ROLLBACK")
                log_error("etl_cvm_zip", type="dfp", error=str(exc))
```

- [ ] **Step 4: Substituir o bloco ITR em `run_ingest_cvm` (linhas 282–304)**

Substituir:

```python
                try:
                    con.execute("BEGIN")
                    if to_insert:
                        con.executemany(
                            "INSERT OR REPLACE INTO cvm_statements"
                            " (cnpj, period, report_type, account_code, account_name,"
                            "  value, currency, source, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            [
                                (r["cnpj"], r["period"], r["report_type"], r["account_code"],
                                 r["account_name"], r["value"], r["currency"], r["source"], fetched_at)
                                for r in to_insert
                            ],
                        )
                    con.execute(
                        "INSERT OR REPLACE INTO raw_files"
                        " (source, path, fetched_at, checksum, size_bytes) VALUES (?, ?, ?, ?, ?)",
                        ["cvm_itr", itr_path, fetched_at, checksum, size_bytes],
                    )
                    con.execute("COMMIT")
                    rows_statements += len(to_insert)
                except Exception as exc:
                    con.execute("ROLLBACK")
                    log_error("etl_cvm_zip", type="itr", error=str(exc))
```

Por:

```python
                try:
                    con.execute("BEGIN")
                    if to_insert:
                        df_itr = pd.DataFrame(to_insert)
                        df_itr["fetched_at"] = fetched_at
                        con.register("_staging_itr", df_itr)
                        con.execute(
                            "INSERT OR REPLACE INTO cvm_statements"
                            " (cnpj, period, report_type, account_code, account_name,"
                            "  value, currency, source, fetched_at)"
                            " SELECT cnpj, period::DATE, report_type, account_code, account_name,"
                            "        value, currency, source, fetched_at"
                            " FROM _staging_itr"
                        )
                        con.unregister("_staging_itr")
                    con.execute(
                        "INSERT OR REPLACE INTO raw_files"
                        " (source, path, fetched_at, checksum, size_bytes) VALUES (?, ?, ?, ?, ?)",
                        ["cvm_itr", itr_path, fetched_at, checksum, size_bytes],
                    )
                    con.execute("COMMIT")
                    rows_statements += len(to_insert)
                except Exception as exc:
                    con.execute("ROLLBACK")
                    log_error("etl_cvm_zip", type="itr", error=str(exc))
```

- [ ] **Step 5: Rodar todos os testes de cvm e confirmar PASS**

```bash
cd /home/paulo/Projetos/b3_llm_report && python -m pytest tests/test_cvm.py -v 2>&1 | tail -15
```

Expected: todos passando. Os testes existentes usam fixtures em memória e não chamam pandas diretamente — devem funcionar sem alteração.

- [ ] **Step 6: Commit**

```bash
git add src/b3_etl/cvm.py requirements-etl.txt
git commit -m "$(cat <<'EOF'
perf: substituir executemany por pandas bulk insert no ingest CVM

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `run_build_ticker_map` — fix de paginação + atualização de fixtures

**Files:**
- Modify: `src/b3_etl/ticker_map.py:93`
- Modify: `tests/test_ticker_map.py`

### Contexto

A API B3 mudou a estrutura: `totalPages` agora está em `data["page"]["totalPages"]`, não em `data["totalPages"]`. O código atual usa `data.get("totalPages", 1)` → sempre retorna `None` (cast para loop `while page <= None` que termina imediatamente) ou nunca pagina. Resultado: apenas a página 1 (120 empresas) é carregada das 3.366 disponíveis.

Os fixtures de teste existentes usam a estrutura antiga (`"totalPages": 2` no nível raiz). Precisam ser atualizados para refletir a estrutura real da API — caso contrário os testes passariam com a implementação errada.

- [ ] **Step 1: Adicionar o teste de paginação em `tests/test_ticker_map.py`**

Adicionar antes de `test_run_build_ticker_map_popula_tabela`:

```python
def test_paginacao_usa_page_totalPages(tmp_path):
    """run_build_ticker_map deve ler totalPages de data['page']['totalPages']."""
    from b3_etl.ticker_map import run_build_ticker_map
    from b3_storage.db import connect

    config = _make_config(str(tmp_path))
    pages_fetched = []

    def _fake(page: int, page_size: int = 120, timeout: int = 30) -> dict:
        pages_fetched.append(page)
        if page == 1:
            return {
                "page": {"pageNumber": 1, "pageSize": 2, "totalRecords": 3, "totalPages": 2},
                "results": [
                    {"issuingCompany": "PETR4", "cnpj": "33000167000101", "companyName": "PETROBRAS S.A."},
                ],
            }
        return {
            "page": {"pageNumber": 2, "pageSize": 2, "totalRecords": 3, "totalPages": 2},
            "results": [
                {"issuingCompany": "VALE3", "cnpj": "33592510000103", "companyName": "VALE S.A."},
            ],
        }

    with patch("b3_etl.ticker_map.fetch_b3_page", side_effect=_fake):
        rc = run_build_ticker_map(config=config)

    assert rc == 0
    assert pages_fetched == [1, 2], f"Expected [1, 2], got {pages_fetched}"

    con = connect(config.db_path, read_only=True)
    count = con.execute("SELECT COUNT(*) FROM ticker_map").fetchone()[0]
    con.close()
    assert count == 2
```

- [ ] **Step 2: Rodar e confirmar FAIL**

```bash
cd /home/paulo/Projetos/b3_llm_report && python -m pytest tests/test_ticker_map.py::test_paginacao_usa_page_totalPages -v 2>&1 | tail -10
```

Expected: FAIL — `AssertionError: Expected [1, 2], got [1]` (loop termina na página 1).

- [ ] **Step 3: Corrigir a linha de paginação em `src/b3_etl/ticker_map.py`**

Na linha 93, substituir:

```python
            total_pages = data.get("totalPages", 1)
```

por:

```python
            total_pages = data.get("page", {}).get("totalPages", 1)
```

- [ ] **Step 4: Rodar o novo teste e confirmar PASS**

```bash
cd /home/paulo/Projetos/b3_llm_report && python -m pytest tests/test_ticker_map.py::test_paginacao_usa_page_totalPages -v 2>&1 | tail -10
```

Expected: PASS.

- [ ] **Step 5: Atualizar os fixtures existentes para a nova estrutura da API**

Em `tests/test_ticker_map.py`, substituir `_FAKE_PAGE_1` e `_FAKE_PAGE_2` por:

```python
_FAKE_PAGE_1 = {
    "page": {"pageNumber": 1, "pageSize": 4, "totalRecords": 5, "totalPages": 2},
    "results": [
        {"issuingCompany": "PETR4", "cnpj": "33000167000101", "companyName": "PETROBRAS S.A."},
        {"issuingCompany": "PETR3", "cnpj": "33000167000101", "companyName": "PETROBRAS S.A."},
        {"issuingCompany": "",      "cnpj": "99999999000100", "companyName": "SEM TICKER"},
        {"issuingCompany": "ITUB4", "cnpj": "",               "companyName": "SEM CNPJ"},
    ],
}

_FAKE_PAGE_2 = {
    "page": {"pageNumber": 2, "pageSize": 4, "totalRecords": 5, "totalPages": 2},
    "results": [
        {"issuingCompany": "VALE3", "cnpj": "33592510000103", "companyName": "VALE S.A."},
    ],
}
```

E atualizar `_fake_page2_fails` em `test_run_build_ticker_map_falha_rede` para retornar a nova estrutura na página 1:

```python
    def _fake_page2_fails(page: int, page_size: int = 120, timeout: int = 30) -> dict:
        if page == 1:
            return _FAKE_PAGE_1  # totalPages agora em data["page"]["totalPages"] = 2
        raise OSError("timeout")
```

(O corpo da função não muda — apenas a estrutura do `_FAKE_PAGE_1` que ela retorna já foi corrigida no passo anterior.)

- [ ] **Step 6: Rodar todos os testes de ticker_map e confirmar PASS**

```bash
cd /home/paulo/Projetos/b3_llm_report && python -m pytest tests/test_ticker_map.py -v 2>&1 | tail -15
```

Expected: todos passando.

- [ ] **Step 7: Rodar suite completa e confirmar sem regressão**

```bash
cd /home/paulo/Projetos/b3_llm_report && python -m pytest tests/ -v 2>&1 | tail -10
```

Expected: todos os testes passando.

- [ ] **Step 8: Commit**

```bash
git add src/b3_etl/ticker_map.py tests/test_ticker_map.py
git commit -m "$(cat <<'EOF'
fix: corrige paginação ticker_map para nova estrutura da API B3

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```
