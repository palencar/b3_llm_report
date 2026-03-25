# Ingestão CVM (DFP/ITR) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar ingestão bulk das demonstrações financeiras da CVM (DFP anual + ITR trimestral) ao pipeline ETL, gravando todas as empresas abertas em duas novas tabelas DuckDB — sem dependências novas.

**Architecture:** `src/b3_etl/cvm.py` contém todo o parsing e orquestração. Duas novas tabelas (`cvm_companies`, `cvm_statements`) são adicionadas ao schema existente. CLI `ingest_cvm.py` segue o mesmo padrão de `ingest.py`. DFP tem precedência sobre ITR: registros ITR são filtrados antes do INSERT se DFP já existe para o mesmo `(cnpj, period, report_type, account_code)`. Valores normalizados para BRL base via `ESCALA_MOEDA`.

**Tech Stack:** Python stdlib (`urllib.request`, `csv`, `zipfile`, `hashlib`, `io`, `re`, `time`), DuckDB (`executemany` para batch), pytest, `unittest.mock`.

---

## Estrutura de arquivos

| Arquivo | Ação |
|---------|------|
| `src/b3_storage/schema.py` | Editar — adicionar DDL + `REQUIRED_TABLES` |
| `src/b3_etl/cvm.py` | Criar — toda a lógica CVM |
| `tests/test_cvm.py` | Criar — todos os testes |
| `ingest_cvm.py` | Criar — CLI entry point |

---

### Task 1: Schema + `parse_companies`

**Files:**
- Modify: `src/b3_storage/schema.py`
- Create: `src/b3_etl/cvm.py`
- Create: `tests/test_cvm.py`

- [ ] **Step 1: Escrever testes falhando**

Criar `tests/test_cvm.py`:

```python
"""Testes para src/b3_etl/cvm.py."""
import hashlib
import io
import os
import zipfile
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

from b3_etl.cvm import parse_companies

# ---------------------------------------------------------------------------
# Helpers para gerar fixtures ZIP em memória
# ---------------------------------------------------------------------------

_CADASTRO_CSV = (
    "CNPJ_CIA;DENOM_SOCIAL;CD_CVM\n"
    "33.000.167/0001-01;PETROBRAS S.A.;9512\n"
    "60.746.948/0001-12;ITAU UNIBANCO HOLDING S.A.;7617\n"
    "33.592.510/0001-03;VALE S.A.;4170\n"
)

_DFP_BPA_CSV = (
    "CNPJ_CIA;DT_REFER;ORDEM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;MOEDA;ESCALA_MOEDA\n"
    "33.000.167/0001-01;2024-12-31;ÚLTIMO;1;Ativo Total;100000;REAL;MIL\n"
    "33.000.167/0001-01;2024-12-31;PENÚLTIMO;1;Ativo Total;90000;REAL;MIL\n"
    "60.746.948/0001-12;2024-12-31;ÚLTIMO;1;Ativo Total;200000;REAL;MIL\n"
    "33.592.510/0001-03;2024-12-31;ÚLTIMO;1;Ativo Total;150000;REAL;MIL\n"
    "33.000.167/0001-01;2024-12-31;ÚLTIMO;1.01;Ativo Circulante;20000;REAL;MIL\n"
)

_ITR_BPA_CSV = (
    "CNPJ_CIA;DT_REFER;ORDEM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;MOEDA;ESCALA_MOEDA\n"
    "33.000.167/0001-01;2024-12-31;ÚLTIMO;1;Ativo Total;99000;REAL;MIL\n"
    "33.000.167/0001-01;2024-12-31;ÚLTIMO;1.02;Novo Campo ITR;5000;REAL;MIL\n"
)


def _zip_bytes(files: dict) -> bytes:
    """Create a ZIP in memory. files: {filename: content_str (latin-1 encoded)}."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content.encode("latin-1"))
    return buf.getvalue()


def _make_cadastro_zip(tmp_path: str) -> str:
    path = os.path.join(tmp_path, "cia_aberta.zip")
    with open(path, "wb") as f:
        f.write(_zip_bytes({"cia_aberta.csv": _CADASTRO_CSV}))
    return path


def _make_dfp_zip(tmp_path: str) -> str:
    path = os.path.join(tmp_path, "dfp_sample.zip")
    with open(path, "wb") as f:
        f.write(_zip_bytes({"dfp_cia_aberta_2024_BPA.csv": _DFP_BPA_CSV}))
    return path


def _make_itr_zip(tmp_path: str) -> str:
    path = os.path.join(tmp_path, "itr_sample.zip")
    with open(path, "wb") as f:
        f.write(_zip_bytes({"itr_cia_aberta_2024_BPA.csv": _ITR_BPA_CSV}))
    return path


def _init_db(db_path: str) -> None:
    from b3_storage.schema import SCHEMA_SQL
    from b3_storage.db import connect
    con = connect(db_path, read_only=False)
    for stmt in SCHEMA_SQL.split(";"):
        stmt = stmt.strip()
        if stmt:
            con.execute(stmt)
    con.close()


# ---------------------------------------------------------------------------
# Task 1: parse_companies
# ---------------------------------------------------------------------------

def test_parse_companies(tmp_path):
    zip_path = _make_cadastro_zip(str(tmp_path))
    result = parse_companies(zip_path)
    assert len(result) == 3
    cnpjs = {r["cnpj"] for r in result}
    assert "33.000.167/0001-01" in cnpjs
    assert "60.746.948/0001-12" in cnpjs
    assert "33.592.510/0001-03" in cnpjs
    petr = next(r for r in result if r["cnpj"] == "33.000.167/0001-01")
    assert petr["name"] == "PETROBRAS S.A."
    assert petr["cd_cvm"] == "9512"
```

- [ ] **Step 2: Executar — deve falhar**

```bash
python -m pytest tests/test_cvm.py::test_parse_companies -v
```

Esperado: `ImportError: cannot import name 'parse_companies' from 'b3_etl.cvm'`

- [ ] **Step 3: Atualizar `src/b3_storage/schema.py`**

Adicionar as duas novas tabelas ao `SCHEMA_SQL` e ao `REQUIRED_TABLES`:

```python
REQUIRED_TABLES = [
    "companies",
    "fundamentals",
    "prices",
    "ratios",
    "raw_files",
    "cvm_companies",
    "cvm_statements",
]

SCHEMA_SQL = """
-- companies
CREATE TABLE IF NOT EXISTS companies (
    ticker TEXT PRIMARY KEY,
    name TEXT,
    sector TEXT,
    industry TEXT,
    last_update TIMESTAMP,
    source TEXT,
    updated_at TIMESTAMP
);

-- fundamentals
CREATE TABLE IF NOT EXISTS fundamentals (
    ticker TEXT,
    period DATE,
    statement_type TEXT,
    key TEXT,
    value DOUBLE,
    currency TEXT,
    source TEXT,
    fetched_at TIMESTAMP,
    PRIMARY KEY (ticker, period, statement_type, key)
);

-- prices
CREATE TABLE IF NOT EXISTS prices (
    ticker TEXT,
    ts TIMESTAMP,
    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE,
    volume BIGINT,
    source TEXT,
    PRIMARY KEY (ticker, ts)
);

-- ratios
CREATE TABLE IF NOT EXISTS ratios (
    ticker TEXT,
    period DATE,
    ratio_name TEXT,
    value DOUBLE,
    computed_at TIMESTAMP,
    PRIMARY KEY (ticker, period, ratio_name)
);

-- raw_files
CREATE TABLE IF NOT EXISTS raw_files (
    source TEXT,
    path TEXT,
    fetched_at TIMESTAMP,
    checksum TEXT,
    size_bytes BIGINT,
    PRIMARY KEY (source, path)
);

-- cvm_companies
CREATE TABLE IF NOT EXISTS cvm_companies (
    cnpj        TEXT PRIMARY KEY,
    name        TEXT,
    cd_cvm      TEXT,
    fetched_at  TIMESTAMP
);

-- cvm_statements
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
""".strip()
```

- [ ] **Step 4: Criar `src/b3_etl/cvm.py` com `parse_companies`**

```python
"""Ingestão CVM (DFP/ITR) — download, parse e gravação no DuckDB."""
import csv
import hashlib
import io
import os
import re
import time
import urllib.request
import zipfile
from datetime import datetime, timezone

from b3_core.config import Config
from b3_core.log import log_info, log_error
from b3_storage.db import connect, missing_tables

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_REPORT_TYPES = frozenset({"BPA", "BPP", "DRE", "DFC_MI", "DFC_MD", "DVA", "DMPL", "DRA"})

_SCALE = {"UNIDADE": 1, "MIL": 1_000, "MILHÃO": 1_000_000}

_CADASTRO_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cia_aberta.zip"
_DFP_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_{year}.zip"
_ITR_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/itr_cia_aberta_{year}.zip"

# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _extract_report_type(filename: str) -> str | None:
    """Extract report type from CSV filename.

    Examples:
        'dfp_cia_aberta_2024_BPA_con.csv' → 'BPA'
        'itr_cia_aberta_2024_DFC_MI.csv'  → 'DFC_MI'
    """
    upper = filename.upper()
    # Try multi-word types first to avoid partial matches (DFC_MI before DFC)
    for rt in sorted(_REPORT_TYPES, key=len, reverse=True):
        if re.search(rf"_{re.escape(rt)}[_.]", upper):
            return rt
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_companies(zip_path: str) -> list[dict]:
    """Parse cia_aberta.zip. Returns list of {cnpj, name, cd_cvm}."""
    result = []
    with zipfile.ZipFile(zip_path) as zf:
        csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not csv_names:
            return result
        with zf.open(csv_names[0]) as raw:
            reader = csv.DictReader(
                io.TextIOWrapper(raw, encoding="latin-1"), delimiter=";"
            )
            for row in reader:
                cnpj = row.get("CNPJ_CIA", "").strip()
                if not cnpj:
                    continue
                result.append({
                    "cnpj": cnpj,
                    "name": row.get("DENOM_SOCIAL", "").strip(),
                    "cd_cvm": row.get("CD_CVM", "").strip(),
                })
    return result
```

- [ ] **Step 5: Executar — deve passar**

```bash
python -m pytest tests/test_cvm.py::test_parse_companies -v
```

Esperado: `1 passed`

- [ ] **Step 6: Commit**

```bash
git add src/b3_storage/schema.py src/b3_etl/cvm.py tests/test_cvm.py
git commit -m "feat: schema CVM (cvm_companies, cvm_statements) + parse_companies"
```

---

### Task 2: `parse_statements`

**Files:**
- Modify: `src/b3_etl/cvm.py`
- Modify: `tests/test_cvm.py`

- [ ] **Step 1: Escrever testes falhando**

Adicionar ao final de `tests/test_cvm.py`:

```python
from b3_etl.cvm import parse_statements
from datetime import date


def test_parse_statements_dfp(tmp_path):
    """Extrai registros DFP, normaliza ESCALA_MOEDA=MIL e filtra PENÚLTIMO."""
    zip_path = _make_dfp_zip(str(tmp_path))
    result = parse_statements(zip_path, "cvm_dfp")

    # Apenas ÚLTIMO: PETR4(1), PETR4(1.01), ITUB4(1), VALE3(1)  — sem PENÚLTIMO
    assert len(result) == 4
    petr_ativo = next(
        r for r in result
        if r["cnpj"] == "33.000.167/0001-01" and r["account_code"] == "1"
    )
    assert petr_ativo["report_type"] == "BPA"
    assert petr_ativo["period"] == date(2024, 12, 31)
    # 100000 × 1000 (MIL) = 100_000_000
    assert petr_ativo["value"] == 100_000_000.0
    assert petr_ativo["currency"] == "REAL"
    assert petr_ativo["source"] == "cvm_dfp"
    assert petr_ativo["account_name"] == "Ativo Total"


def test_parse_statements_filtra_penultimo(tmp_path):
    """ORDEM_EXERC='PENÚLTIMO' não é incluído no resultado."""
    zip_path = _make_dfp_zip(str(tmp_path))
    result = parse_statements(zip_path, "cvm_dfp")
    # O CSV tem 5 linhas ÚLTIMO e 1 PENÚLTIMO → resultado deve ter 4 (1 PETR4 account_code=1,
    # 1 PETR4 account_code=1.01, 1 ITUB4, 1 VALE3)
    penultimos = [r for r in result if r["account_code"] == "1" and r["cnpj"] == "33.000.167/0001-01"]
    # Deve haver exatamente 1 (o ÚLTIMO), não 2
    assert len(penultimos) == 1
    assert penultimos[0]["value"] == 100_000_000.0
```

- [ ] **Step 2: Executar — devem falhar**

```bash
python -m pytest tests/test_cvm.py::test_parse_statements_dfp tests/test_cvm.py::test_parse_statements_filtra_penultimo -v
```

Esperado: `ImportError: cannot import name 'parse_statements'`

- [ ] **Step 3: Implementar `parse_statements` em `src/b3_etl/cvm.py`**

Adicionar após `parse_companies`:

```python
def parse_statements(zip_path: str, source: str) -> list[dict]:
    """Parse DFP/ITR ZIP. Returns list of statement records.

    Filters ORDEM_EXERC == 'ÚLTIMO'. Normalizes VL_CONTA by ESCALA_MOEDA.
    period is returned as datetime.date.
    """
    result = []
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if not name.lower().endswith(".csv"):
                continue
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
                    result.append({
                        "cnpj": cnpj,
                        "period": period,
                        "report_type": report_type,
                        "account_code": cd_conta,
                        "account_name": ds_conta,
                        "value": value,
                        "currency": moeda,
                        "source": source,
                    })
    return result
```

- [ ] **Step 4: Executar — devem passar**

```bash
python -m pytest tests/test_cvm.py::test_parse_statements_dfp tests/test_cvm.py::test_parse_statements_filtra_penultimo -v
```

Esperado: `2 passed`

- [ ] **Step 5: Executar suíte completa para garantir nada quebrou**

```bash
python -m pytest tests/ -q
```

Esperado: todos os testes passando

- [ ] **Step 6: Commit**

```bash
git add src/b3_etl/cvm.py tests/test_cvm.py
git commit -m "feat: parse_statements CVM com filtro ORDEM_EXERC e normalização ESCALA_MOEDA"
```

---

### Task 3: `download_zip` + `_download_or_skip` + `run_ingest_cvm`

**Files:**
- Modify: `src/b3_etl/cvm.py`
- Modify: `tests/test_cvm.py`

- [ ] **Step 1: Escrever testes falhando**

Adicionar ao final de `tests/test_cvm.py`:

```python
from b3_etl.cvm import run_ingest_cvm
from b3_core.config import load_config
from b3_storage.db import connect


def _fake_download_factory(tmp_path: str):
    """Returns a fake download_zip that writes fixture ZIPs based on URL."""
    def _fake(url, dest_path, timeout=60):
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        if "CAD" in url:
            content = _zip_bytes({"cia_aberta.csv": _CADASTRO_CSV})
        elif "DFP" in url:
            content = _zip_bytes({"dfp_cia_aberta_2024_BPA.csv": _DFP_BPA_CSV})
        else:  # ITR
            content = _zip_bytes({"itr_cia_aberta_2024_BPA.csv": _ITR_BPA_CSV})
        with open(dest_path, "wb") as f:
            f.write(content)
        return hashlib.sha256(content).hexdigest(), len(content)
    return _fake


def _make_config(tmp_path: str):
    config = load_config()
    db_path = os.path.join(tmp_path, "test.duckdb")
    _init_db(db_path)
    return config.__class__(
        **{
            **config.__dict__,
            "db_path": db_path,
            "raw_dir": os.path.join(tmp_path, "raw"),
        }
    )


def test_run_ingest_cvm_popula_tabelas(tmp_path):
    """run_ingest_cvm deve gravar cvm_companies e cvm_statements no DuckDB."""
    config = _make_config(str(tmp_path))
    with patch("b3_etl.cvm.download_zip", side_effect=_fake_download_factory(str(tmp_path))):
        rc = run_ingest_cvm(year=2024, include_itr=False, config=config)
    assert rc == 0

    con = connect(config.db_path, read_only=True)
    companies = con.execute("SELECT COUNT(*) FROM cvm_companies").fetchone()[0]
    statements = con.execute("SELECT COUNT(*) FROM cvm_statements").fetchone()[0]
    raw = con.execute("SELECT COUNT(*) FROM raw_files WHERE source IN ('cvm_cadastro','cvm_dfp')").fetchone()[0]
    con.close()

    assert companies == 3
    assert statements == 4   # 4 linhas ÚLTIMO no DFP fixture
    assert raw == 2           # 1 cadastro + 1 dfp


def test_precedencia_dfp_sobre_itr(tmp_path):
    """ITR não deve sobrescrever registros DFP para o mesmo período."""
    config = _make_config(str(tmp_path))
    with patch("b3_etl.cvm.download_zip", side_effect=_fake_download_factory(str(tmp_path))):
        rc = run_ingest_cvm(year=2024, include_itr=True, config=config)
    assert rc == 0

    con = connect(config.db_path, read_only=True)
    # DFP value para PETR4, BPA, conta 1 = 100_000_000
    row = con.execute(
        "SELECT value, source FROM cvm_statements "
        "WHERE cnpj = '33.000.167/0001-01' AND account_code = '1' AND report_type = 'BPA'"
    ).fetchall()
    con.close()

    # Deve haver apenas 1 registro (o DFP); o ITR para o mesmo (cnpj,period,report_type,account_code)
    # deve ter sido filtrado, mas o campo novo (1.02) do ITR pode estar presente
    dfp_rows = [r for r in row if r[1] == "cvm_dfp"]
    itr_rows_conta1 = [r for r in row if r[1] == "cvm_itr" and r[0] == 99_000_000.0]
    assert len(dfp_rows) == 1
    assert dfp_rows[0][0] == 100_000_000.0
    assert len(itr_rows_conta1) == 0  # ITR para conta_code=1 não inserido


def test_run_ingest_cvm_skip_download(tmp_path):
    """Segunda execução não deve chamar download_zip se checksum bate."""
    config = _make_config(str(tmp_path))
    fake = _fake_download_factory(str(tmp_path))
    call_count = {"n": 0}

    def counting_fake(url, dest_path, timeout=60):
        call_count["n"] += 1
        return fake(url, dest_path, timeout)

    with patch("b3_etl.cvm.download_zip", side_effect=counting_fake):
        run_ingest_cvm(year=2024, include_itr=False, config=config)
        first_calls = call_count["n"]
        run_ingest_cvm(year=2024, include_itr=False, config=config)
        second_calls = call_count["n"] - first_calls

    assert first_calls == 2    # cadastro + dfp
    assert second_calls == 0   # ambos pulados (checksum idêntico)


def test_run_ingest_cvm_falha_rede(tmp_path):
    """OSError no download → rc=0, erro logado, banco intacto."""
    config = _make_config(str(tmp_path))
    with patch("b3_etl.cvm.download_zip", side_effect=OSError("timeout")):
        rc = run_ingest_cvm(year=2024, include_itr=False, config=config)
    assert rc == 0

    con = connect(config.db_path, read_only=True)
    companies = con.execute("SELECT COUNT(*) FROM cvm_companies").fetchone()[0]
    con.close()
    assert companies == 0  # nada gravado, mas sem crash
```

- [ ] **Step 2: Executar — devem falhar**

```bash
python -m pytest tests/test_cvm.py::test_run_ingest_cvm_popula_tabelas tests/test_cvm.py::test_precedencia_dfp_sobre_itr tests/test_cvm.py::test_run_ingest_cvm_skip_download tests/test_cvm.py::test_run_ingest_cvm_falha_rede -v
```

Esperado: `ImportError: cannot import name 'run_ingest_cvm'`

- [ ] **Step 3: Implementar `download_zip`, `_download_or_skip`, `run_ingest_cvm` em `src/b3_etl/cvm.py`**

Adicionar após `parse_statements`:

```python
def download_zip(url: str, dest_path: str, timeout: int = 60) -> tuple[str, int]:
    """Download ZIP from url to dest_path. Returns (checksum_sha256, size_bytes).

    Raises OSError on network failure.
    """
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "b3-llm-report/etl"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    with open(dest_path, "wb") as f:
        f.write(data)
    return hashlib.sha256(data).hexdigest(), len(data)


def _download_or_skip(
    url: str,
    dest_path: str,
    con,
    source: str,
    timeout: int = 60,
) -> tuple[str, int, bool]:
    """Download ZIP or skip if already cached in raw_files with matching checksum.

    con: DuckDB connection or None (skip_db mode → always download).
    Returns (checksum, size_bytes, was_downloaded).
    """
    if con is not None and os.path.isfile(dest_path):
        row = con.execute(
            "SELECT checksum FROM raw_files WHERE source = ? AND path = ?",
            [source, dest_path],
        ).fetchone()
        if row:
            with open(dest_path, "rb") as f:
                local_checksum = hashlib.sha256(f.read()).hexdigest()
            if local_checksum == row[0]:
                return local_checksum, os.path.getsize(dest_path), False
    checksum, size_bytes = download_zip(url, dest_path, timeout=timeout)
    return checksum, size_bytes, True


def run_ingest_cvm(
    year: int,
    include_itr: bool,
    config: Config,
    skip_db: bool = False,
) -> int:
    """Orchestrate CVM ingestion: cadastro → DFP → ITR (optional).

    Returns rc=0 always. Errors are logged and non-fatal.
    """
    log_info("etl_cvm_start", year=year, include_itr=include_itr)
    t0 = time.time()

    con = None
    if not skip_db:
        con = connect(config.db_path, read_only=False)
        missing = missing_tables(con)
        if missing:
            log_error("etl_cvm_start", error=f"tabelas ausentes: {missing}")
            con.close()
            return 1

    fetched_at = datetime.now(timezone.utc).replace(tzinfo=None)
    rows_companies = 0
    rows_statements = 0

    cvm_dir = os.path.join(config.raw_dir, "cvm")
    cadastro_path = os.path.join(cvm_dir, "cadastro", "cia_aberta.zip")
    dfp_path = os.path.join(cvm_dir, str(year), f"dfp_cia_aberta_{year}.zip")
    itr_path = os.path.join(cvm_dir, str(year), f"itr_cia_aberta_{year}.zip")

    # 1. Cadastro
    try:
        checksum, size_bytes, _ = _download_or_skip(
            _CADASTRO_URL, cadastro_path, con, "cvm_cadastro"
        )
        companies = parse_companies(cadastro_path)
        log_info("etl_cvm_zip", type="cadastro", rows=len(companies), size_bytes=size_bytes)
        if con and companies:
            try:
                con.execute("BEGIN")
                con.executemany(
                    "INSERT OR REPLACE INTO cvm_companies"
                    " (cnpj, name, cd_cvm, fetched_at) VALUES (?, ?, ?, ?)",
                    [(c["cnpj"], c["name"], c["cd_cvm"], fetched_at) for c in companies],
                )
                con.execute(
                    "INSERT OR REPLACE INTO raw_files"
                    " (source, path, fetched_at, checksum, size_bytes) VALUES (?, ?, ?, ?, ?)",
                    ["cvm_cadastro", cadastro_path, fetched_at, checksum, size_bytes],
                )
                con.execute("COMMIT")
                rows_companies = len(companies)
            except Exception as exc:
                con.execute("ROLLBACK")
                log_error("etl_cvm_zip", type="cadastro", error=str(exc))
    except OSError as exc:
        log_error("etl_cvm_zip", type="cadastro", error=str(exc))

    # 2. DFP
    try:
        checksum, size_bytes, _ = _download_or_skip(
            _DFP_URL.format(year=year), dfp_path, con, "cvm_dfp"
        )
        dfp_records = parse_statements(dfp_path, "cvm_dfp")
        log_info("etl_cvm_zip", type="dfp", year=year, rows=len(dfp_records), size_bytes=size_bytes)
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
    except OSError as exc:
        log_error("etl_cvm_zip", type="dfp", error=str(exc))

    # 3. ITR (optional)
    if include_itr:
        try:
            checksum, size_bytes, _ = _download_or_skip(
                _ITR_URL.format(year=year), itr_path, con, "cvm_itr"
            )
            itr_records = parse_statements(itr_path, "cvm_itr")
            if con:
                existing = con.execute(
                    "SELECT cnpj, period, report_type, account_code"
                    " FROM cvm_statements WHERE source = 'cvm_dfp'"
                ).fetchall()
                existing_set = {(r[0], r[1], r[2], r[3]) for r in existing}
                to_insert = [
                    r for r in itr_records
                    if (r["cnpj"], r["period"], r["report_type"], r["account_code"])
                    not in existing_set
                ]
                log_info(
                    "etl_cvm_zip", type="itr", year=year,
                    rows_parsed=len(itr_records), rows_inserted=len(to_insert),
                    size_bytes=size_bytes,
                )
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
        except OSError as exc:
            log_error("etl_cvm_zip", type="itr", error=str(exc))

    if con:
        con.close()

    duration_ms = int((time.time() - t0) * 1000)
    log_info(
        "etl_cvm_done",
        rows_companies=rows_companies,
        rows_statements=rows_statements,
        duration_ms=duration_ms,
    )
    return 0
```

- [ ] **Step 4: Executar — devem passar**

```bash
python -m pytest tests/test_cvm.py -v
```

Esperado: `7 passed`

- [ ] **Step 5: Executar suíte completa**

```bash
python -m pytest tests/ -q
```

Esperado: todos os testes passando

- [ ] **Step 6: Commit**

```bash
git add src/b3_etl/cvm.py tests/test_cvm.py
git commit -m "feat: download_zip, _download_or_skip e run_ingest_cvm com precedência DFP"
```

---

### Task 4: CLI `ingest_cvm.py`

**Files:**
- Create: `ingest_cvm.py`

- [ ] **Step 1: Criar `ingest_cvm.py`**

```python
import argparse
import os
import sys

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from b3_core.config import load_config
from b3_etl.cvm import run_ingest_cvm


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingestão bulk CVM (DFP/ITR) para dados fundamentalistas."
    )
    parser.add_argument(
        "--year",
        type=int,
        required=True,
        help="Ano de referência (ex: 2024).",
    )
    parser.add_argument(
        "--itr",
        action="store_true",
        help="Incluir ITR trimestral além do DFP anual.",
    )
    parser.add_argument(
        "--skip-db",
        action="store_true",
        help="Não gravar no DuckDB (mantém apenas raw files).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    config = load_config()
    return run_ingest_cvm(
        year=args.year,
        include_itr=args.itr,
        config=config,
        skip_db=args.skip_db,
    )


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Verificar sintaxe**

```bash
python -m py_compile ingest_cvm.py src/b3_etl/cvm.py
```

Esperado: sem saída (silencioso = sucesso)

- [ ] **Step 3: Executar suíte completa**

```bash
python -m pytest tests/ -v
```

Esperado: todos os testes passando

- [ ] **Step 4: Verificar que `init_db.py` cria as novas tabelas**

```bash
python init_db.py
python -c "
import sys; sys.path.insert(0, 'src')
import duckdb
con = duckdb.connect('data/duckdb/b3_fundamentals.duckdb', read_only=True)
tables = con.execute(\"SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'cvm%'\").fetchall()
print('Tabelas CVM:', tables)
con.close()
"
```

Esperado: `Tabelas CVM: [('cvm_companies',), ('cvm_statements',)]`

- [ ] **Step 5: Commit**

```bash
git add ingest_cvm.py
git commit -m "feat: CLI ingest_cvm.py para ingestão bulk CVM (DFP/ITR)"
```

---

## Comandos para teste manual (após implementação)

```bash
# 1. Recriar DB com novas tabelas (idempotente)
python init_db.py

# 2. Ingerir DFP 2024
python ingest_cvm.py --year 2024

# 3. Verificar empresas
python -c "
import sys; sys.path.insert(0, 'src')
import duckdb
con = duckdb.connect('data/duckdb/b3_fundamentals.duckdb', read_only=True)
print(con.execute('SELECT COUNT(*) FROM cvm_companies').fetchone())
print(con.execute(\"SELECT name, cd_cvm FROM cvm_companies LIMIT 5\").fetchall())
con.close()
"

# 4. Verificar demonstrações
python -c "
import sys; sys.path.insert(0, 'src')
import duckdb
con = duckdb.connect('data/duckdb/b3_fundamentals.duckdb', read_only=True)
print(con.execute('SELECT COUNT(*) FROM cvm_statements').fetchone())
print(con.execute(\"SELECT report_type, COUNT(*) FROM cvm_statements GROUP BY report_type ORDER BY 1\").fetchall())
con.close()
"
```
