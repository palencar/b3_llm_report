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
| `src/b3_storage/schema.py` | Editar — adicionar DDL das 2 novas tabelas e incluir em `REQUIRED_TABLES` |

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

**`value`**: sempre em unidade monetária base (BRL), após normalização pela escala — ver seção "Normalização de valores".

**`REQUIRED_TABLES`**: `cvm_companies` e `cvm_statements` são adicionadas à lista `REQUIRED_TABLES` em `schema.py`. Bancos existentes precisam executar `python init_db.py` novamente para criar as novas tabelas — `init_db.py` usa `CREATE TABLE IF NOT EXISTS`, portanto é idempotente.

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
    #   CNPJ_CIA → cnpj
    #   DT_REFER → period (datetime.date, via datetime.strptime(v, "%Y-%m-%d").date())
    #   ORDEM_EXERC → filtro: manter apenas 'ÚLTIMO'
    #   CD_CONTA → account_code
    #   DS_CONTA → account_name
    #   VL_CONTA → value (float, após normalização por ESCALA_MOEDA)
    #   MOEDA → currency
    #   ESCALA_MOEDA → escala para normalização (ver seção abaixo)
    # report_type extraído do nome do arquivo (ex: '_BPA.csv' → 'BPA')
    # Retorna lista de {cnpj, period, report_type, account_code, account_name, value, currency, source}

def run_ingest_cvm(year: int, include_itr: bool, config: Config, skip_db: bool) -> int
    # Orquestra: cadastro → DFP → ITR (se --itr)
    # Retorna rc=0 (erros são logados, não fatais)
```

---

## Normalização de valores (`ESCALA_MOEDA`)

Os CSVs da CVM incluem o campo `ESCALA_MOEDA` que define a unidade dos valores em `VL_CONTA`. Todos os valores devem ser normalizados para BRL base antes de armazenar:

| `ESCALA_MOEDA` | Multiplicador |
|---|---|
| `UNIDADE` | 1 |
| `MIL` | 1_000 |
| `MILHÃO` | 1_000_000 |

```python
_SCALE = {"UNIDADE": 1, "MIL": 1_000, "MILHÃO": 1_000_000}
value = float(row["VL_CONTA"].replace(",", ".")) * _SCALE.get(row["ESCALA_MOEDA"], 1)
```

Linhas com `VL_CONTA` vazio ou não numérico são ignoradas silenciosamente.

---

## Fluxo de execução

```
run_ingest_cvm(year, include_itr, config, skip_db)
│
├── _download_or_skip(cadastro_url, dest_path)
│   └── parse_companies() → batch upsert cvm_companies (BEGIN/COMMIT)
│       └── registra em raw_files
│
├── _download_or_skip(dfp_url, dest_path)
│   └── parse_statements(source='cvm_dfp') → batch insert cvm_statements (BEGIN/COMMIT)
│       └── registra em raw_files
│
└── [se --itr] _download_or_skip(itr_url, dest_path)
    └── parse_statements(source='cvm_itr')
        → filtra registros onde já existe DFP (ver "Precedência DFP")
        → batch insert registros restantes (BEGIN/COMMIT)
        └── registra em raw_files
```

**`_download_or_skip`:** função interna que verifica se o arquivo de destino já existe (`dest_path` fixo, sem timestamp). Lógica:
1. Se o arquivo **não existe** no disco → baixa normalmente.
2. Se o arquivo **existe** no disco → verifica se há entrada correspondente em `raw_files` com o mesmo `path`:
   - Se existe e o checksum bate → pula o download, retorna caminho existente.
   - Se **não existe em `raw_files`** (falha parcial anterior) ou checksum diverge → baixa novamente, sobrescreve o arquivo.

Os nomes dos ZIPs são fixos (sem timestamp) para permitir a comparação por caminho:
- `data/raw/cvm/cadastro/cia_aberta.zip`
- `data/raw/cvm/{year}/dfp_cia_aberta_{year}.zip`
- `data/raw/cvm/{year}/itr_cia_aberta_{year}.zip`

O timestamp é registrado apenas em `raw_files.fetched_at` (momento do download).

---

## Precedência DFP sobre ITR

A PRIMARY KEY de `cvm_statements` inclui `source`, portanto `(cnpj, period, report_type, account_code, 'cvm_dfp')` e `(cnpj, period, report_type, account_code, 'cvm_itr')` são linhas distintas — `INSERT OR IGNORE` **não** implementa a precedência pretendida.

A lógica correta é um **filtro antes do INSERT**: após parsear o ZIP ITR, excluir da lista de registros a inserir aqueles cuja PK natural `(cnpj, period, report_type, account_code)` já existe com `source='cvm_dfp'`. Implementação:

```python
# Após parse_statements(itr_zip, 'cvm_itr') → itr_records
existing = con.execute("""
    SELECT cnpj, period, report_type, account_code
    FROM cvm_statements WHERE source = 'cvm_dfp'
""").fetchall()
existing_set = {(r[0], r[1], r[2], r[3]) for r in existing}
to_insert = [
    r for r in itr_records
    if (r["cnpj"], r["period"], r["report_type"], r["account_code"]) not in existing_set
]
# batch insert to_insert
```

---

## Gravação no DuckDB

### Tabela `cvm_companies`

Batch upsert via `executemany` com `INSERT OR REPLACE INTO cvm_companies VALUES (?, ?, ?, ?)`.
DuckDB suporta `INSERT OR REPLACE` nativamente (diferente de SQLite's `ON CONFLICT DO UPDATE`).

### Tabela `cvm_statements`

**Não usar `_delete_then_insert` row-by-row** — volume potencial de milhões de linhas tornaria isso impraticável. Usar `executemany` com batch de registros dentro de uma única transação:

```python
con.execute("BEGIN")
con.executemany(
    "INSERT OR REPLACE INTO cvm_statements VALUES (?,?,?,?,?,?,?,?,?)",
    [(r["cnpj"], r["period"], r["report_type"], r["account_code"],
      r["account_name"], r["value"], r["currency"], r["source"], fetched_at)
     for r in records]
)
con.execute("COMMIT")
```

Para o caso ITR (com filtro DFP aplicado), o mesmo padrão com a lista `to_insert` já filtrada.

### Tabela `raw_files`

`_delete_then_insert` existente por `(source, path)` — volume unitário por ZIP, padrão existente adequado.

---

## Tratamento de erros

| Situação | Comportamento |
|---|---|
| Falha de rede no download | `log_error("etl_cvm_zip", ...)` + continua para próximo ZIP |
| CSV com coluna ausente | campo ignorado silenciosamente |
| `VL_CONTA` não numérico ou vazio | linha ignorada silenciosamente |
| `ESCALA_MOEDA` desconhecida | multiplicador 1 (sem escala), linha gravada |
| Falha de transação DuckDB | ROLLBACK + `log_error` + continua |
| `rc` final | sempre 0 — erros visíveis nos logs |

---

## Raw files

ZIPs salvos em (nomes fixos, sem timestamp):
- `data/raw/cvm/cadastro/cia_aberta.zip`
- `data/raw/cvm/{year}/dfp_cia_aberta_{year}.zip`
- `data/raw/cvm/{year}/itr_cia_aberta_{year}.zip`

Registrados em `raw_files` com `source='cvm_cadastro'`, `'cvm_dfp'` ou `'cvm_itr'` e `fetched_at` do momento do download.

---

## Logs estruturados

```json
{"level": "info", "job": "etl_cvm_start", "year": 2024, "include_itr": false}
{"level": "info", "job": "etl_cvm_zip", "type": "dfp", "url": "...", "size_bytes": 12345678, "rows": 980000}
{"level": "info", "job": "etl_cvm_done", "rows_companies": 1024, "rows_statements": 4820000, "duration_ms": 45000}
```

---

## Dependências

Nenhuma nova. `urllib`, `csv`, `zipfile` são stdlib. `duckdb` já em `requirements-etl.txt`.

---

## Testes

Fixtures estáticas em `tests/fixtures/cvm/`:
- `cia_aberta_sample.zip` — cadastro com 3 empresas (CNPJs de PETR4, ITUB4, VALE3)
- `dfp_sample.zip` — DFP com BPA + DRE para as 3 empresas, 1 período, ESCALA_MOEDA=MIL
- `itr_sample.zip` — ITR com BPA + DRE para as 3 empresas, mesmo período (para testar precedência DFP)

Os ZIPs de fixture são gerados programaticamente no próprio módulo de teste usando `zipfile` + `io.StringIO` — não requerem arquivos binários committed.

| Teste | O que verifica |
|-------|---------------|
| `test_parse_companies` | 3 empresas extraídas com CNPJ, name, cd_cvm corretos |
| `test_parse_statements_dfp` | report_type correto, period parseado, value normalizado (MIL → ×1000) |
| `test_parse_statements_filtra_penultimo` | apenas registros `ORDEM_EXERC='ÚLTIMO'` retornados |
| `test_precedencia_dfp_sobre_itr` | DuckDB tmp: após inserir DFP e tentar inserir ITR para mesmo período, apenas DFP persiste |
| `test_run_ingest_cvm_popula_tabelas` | DuckDB tmp: cvm_companies + cvm_statements populadas após run completo |
| `test_run_ingest_cvm_skip_download` | ZIP existente com checksum idêntico não baixado novamente (mock urlopen não chamado) |
| `test_run_ingest_cvm_falha_rede` | OSError no download → rc=0, log_error emitido |

---

## O que não muda

- Schema das tabelas BRAPI existentes (`fundamentals`, `ratios`, `companies`, `prices`, `raw_files`)
- Interface de `run_ingest` (BRAPI)
- `requirements-etl.txt`

---

## Critérios de aceitação

1. `python init_db.py` cria `cvm_companies` e `cvm_statements` em banco novo ou existente (idempotente)
2. `python ingest_cvm.py --year 2024` grava registros em `cvm_companies` e `cvm_statements` com values normalizados
3. `python ingest_cvm.py --year 2024 --itr` não sobrescreve registros DFP com ITR
4. Segunda execução consecutiva é idempotente (skip do download, mesmo resultado no banco)
5. `pytest tests/test_cvm.py -v` — todos os testes passam sem acesso à rede
