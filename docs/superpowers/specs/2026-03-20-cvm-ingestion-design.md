# Design — Ingestão CVM (DFP/ITR)

**Data:** 2026-03-20
**Escopo:** Ingestão bulk das demonstrações financeiras da CVM no pipeline ETL existente

---

## Contexto

O ETL atual ingere dados da BRAPI (cotações, demonstrações financeiras em inglês) e do Fundamentus (ratios calculados). A CVM complementa com dados oficiais das demonstrações financeiras padronizadas (DFP anual e ITR trimestral) em português, estruturados por código de conta hierárquico.

A CVM publica dados em bulk (ZIP com CSVs internos), cobrindo todas as empresas abertas (~700–1000). Não há API por empresa — o fluxo inevitável é download bulk → parse → store. O mapeamento CNPJ → ticker é adiado para iteração futura; os dados ficam acessíveis por CNPJ.

---

## Arquitetura

### Novos arquivos

| Arquivo | Ação |
|---------|------|
| `ingest_cvm.py` | Criar — CLI entry point |
| `src/b3_etl/cvm.py` | Criar — download, parse e ingestão |
| `src/b3_storage/schema.py` | Editar — adicionar DDL das 2 novas tabelas |

### Novas tabelas DuckDB

```sql
CREATE TABLE IF NOT EXISTS cvm_companies (
    cnpj        TEXT PRIMARY KEY,
    name        TEXT,
    cd_cvm      TEXT,
    fetched_at  TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cvm_statements (
    cnpj         TEXT,
    period       DATE,
    report_type  TEXT,
    account_code TEXT,
    account_name TEXT,
    value        DOUBLE,
    currency     TEXT,
    source       TEXT,
    fetched_at   TIMESTAMP,
    PRIMARY KEY (cnpj, period, report_type, account_code, source)
);
```

**`report_type`** corresponde ao nome do CSV interno do ZIP: `BPA`, `BPP`, `DRE`, `DFC_MI`, `DFC_MD`, `DVA`, `DMPL`, `DRA`.

**`source`**: `'cvm_dfp'` para DFP anual, `'cvm_itr'` para ITR trimestral.

---

## CLI

```bash
# DFP anual de 2024 (cadastro + demonstrações)
python ingest_cvm.py --year 2024

# DFP + ITRs trimestrais de 2024
python ingest_cvm.py --year 2024 --itr

# Apenas raw files, sem gravar no DuckDB
python ingest_cvm.py --year 2024 --skip-db
```

---

## Fontes de dados CVM

| Tipo | URL |
|------|-----|
| Cadastro | `https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cia_aberta.zip` |
| DFP anual | `https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_{year}.zip` |
| ITR trimestral | `https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/itr_cia_aberta_{year}.zip` |

O ZIP de DFP/ITR contém múltiplos CSVs internos — um por tipo de demonstração (ex: `dfp_cia_aberta_2024_BPA.csv`). O cadastro contém um único CSV com dados cadastrais de todas as empresas.

---

## Módulo `src/b3_etl/cvm.py`

Quatro funções públicas:

```python
def download_zip(url: str, dest_path: str, timeout: int = 60) -> tuple[str, int]
    # urllib.request, grava ZIP em dest_path
    # Retorna (checksum_sha256, size_bytes)
    # Levanta OSError em falha de rede

def parse_companies(zip_path: str) -> list[dict]
    # Abre ZIP, lê cia_aberta.csv (encoding latin-1, sep=';')
    # Retorna lista de {cnpj, name, cd_cvm}
    # Campos: CNPJ_CIA → cnpj, DENOM_SOCIAL → name, CD_CVM → cd_cvm

def parse_statements(zip_path: str, source: str) -> list[dict]
    # Abre ZIP, itera sobre CSVs internos (*_BPA.csv, *_BPP.csv, etc.)
    # Cada CSV: encoding latin-1, sep=';', campos relevantes:
    #   CNPJ_CIA, DT_REFER (→ period DATE), ORDEM_EXERC, DS_CONTA,
    #   CD_CONTA (→ account_code), VL_CONTA (→ value), MOEDA (→ currency)
    # Filtra ORDEM_EXERC == 'ÚLTIMO' (período mais recente de cada arquivo)
    # Retorna lista de {cnpj, period, report_type, account_code, account_name, value, currency, source}
    # report_type extraído do nome do arquivo (ex: '_BPA.csv' → 'BPA')

def run_ingest_cvm(year: int, include_itr: bool, config: Config, skip_db: bool) -> int
    # Orquestra: cadastro → DFP → ITR (se --itr)
    # Retorna rc=0 (erros são logados, não fatais)
```

---

## Fluxo de execução

```
run_ingest_cvm(year, include_itr, config, skip_db)
│
├── download_zip(cadastro_url) → salva em data/raw/cvm/cadastro/
│   └── parse_companies() → upsert cvm_companies (BEGIN/COMMIT)
│       └── registra em raw_files
│
├── download_zip(dfp_url) → salva em data/raw/cvm/{year}/
│   └── parse_statements(source='cvm_dfp') → upsert cvm_statements (BEGIN/COMMIT)
│       └── registra em raw_files
│
└── [se --itr] download_zip(itr_url) → salva em data/raw/cvm/{year}/
    └── parse_statements(source='cvm_itr')
        → INSERT apenas onde não existe registro com source='cvm_dfp'
           para o mesmo (cnpj, period, report_type, account_code)
        → upsert cvm_statements (BEGIN/COMMIT)
        └── registra em raw_files
```

**Skip de download:** se o ZIP já existe em `data/raw/cvm/` com checksum idêntico, pula o download e reutiliza o arquivo local.

---

## Precedência DFP sobre ITR

Ao inserir registros ITR, verificar existência de registro DFP para a mesma PK natural `(cnpj, period, report_type, account_code)`. Se existir com `source='cvm_dfp'`, pular o registro ITR. Implementado com `INSERT OR IGNORE` ou SELECT prévio antes do INSERT.

---

## Gravação no DuckDB

### Tabela `cvm_companies`

`INSERT OR REPLACE` por `cnpj` (upsert simples — cadastro é estável).

### Tabela `cvm_statements`

`_delete_then_insert` existente em `ingest.py`, com where_cols `[cnpj, period, report_type, account_code, source]`. Para ITR: verificação prévia de existência de registro DFP antes de cada insert.

### Tabela `raw_files`

Mesmo padrão existente: `_delete_then_insert` por `(source, path)`.

---

## Tratamento de erros

| Situação | Comportamento |
|---|---|
| Falha de rede no download | `log_error("etl_cvm_zip", ...)` + continua para próximo ZIP |
| CSV com coluna ausente | campo ignorado silenciosamente |
| Valor não conversível para DOUBLE | linha ignorada, demais gravadas |
| Falha de transação DuckDB | ROLLBACK + `log_error` + continua |
| `rc` final | sempre 0 — erros visíveis nos logs |

---

## Raw files

ZIPs salvos em:
- `data/raw/cvm/cadastro/cia_aberta_{ts}.zip`
- `data/raw/cvm/{year}/dfp_cia_aberta_{year}_{ts}.zip`
- `data/raw/cvm/{year}/itr_cia_aberta_{year}_{ts}.zip`

Registrados em `raw_files` com `source='cvm_dfp'`, `'cvm_itr'` ou `'cvm_cadastro'`.

---

## Logs estruturados

```json
{"level": "info", "job": "etl_cvm_start", "year": 2024, "include_itr": false}
{"level": "info", "job": "etl_cvm_zip", "url": "...", "size_bytes": 12345678, "rows": 980000}
{"level": "info", "job": "etl_cvm_done", "rows_companies": 1024, "rows_statements": 4820000, "duration_ms": 45000}
```

---

## Dependências

Nenhuma nova. `urllib` e `csv` são stdlib. `zipfile` é stdlib. `duckdb` já em `requirements-etl.txt`.

---

## Testes

Fixtures estáticas em `tests/fixtures/cvm/`:
- `cia_aberta_sample.zip` — cadastro com 3 empresas (PETR4/CNPJ, ITUB4/CNPJ, VALE3/CNPJ)
- `dfp_sample.zip` — DFP com BPA + DRE para as 3 empresas, 1 período
- `itr_sample.zip` — ITR com BPA + DRE para as 3 empresas, mesmo período (para testar precedência DFP)

| Teste | O que verifica |
|-------|---------------|
| `test_parse_companies` | 3 empresas extraídas com CNPJ, name, cd_cvm corretos |
| `test_parse_statements_dfp` | report_type correto, period parseado, value float |
| `test_parse_statements_itr_precedencia` | registro ITR não sobrescreve DFP existente |
| `test_run_ingest_cvm_popula_tabelas` | DuckDB tmp com cvm_companies + cvm_statements após run |
| `test_run_ingest_cvm_skip_download` | ZIP já existente com mesmo checksum não baixado novamente |
| `test_run_ingest_cvm_falha_rede` | OSError no download → rc=0, log_error emitido |

---

## O que não muda

- Schema das tabelas BRAPI existentes (`fundamentals`, `ratios`, `companies`, `prices`, `raw_files`)
- Interface de `run_ingest` (BRAPI)
- `requirements-etl.txt`

---

## Critérios de aceitação

1. `python ingest_cvm.py --year 2024` grava registros em `cvm_companies` e `cvm_statements`
2. `python ingest_cvm.py --year 2024 --itr` não sobrescreve registros DFP com ITR
3. Execução repetida é idempotente (mesmo resultado)
4. `pytest tests/test_cvm.py -v` — todos os testes passam sem acesso à rede
