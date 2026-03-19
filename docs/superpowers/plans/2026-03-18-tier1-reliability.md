# Tier 1 Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar retry no ETL, stale threshold e fallback degradado no MCP, e logging JSON padronizado compartilhado entre ETL e MCP.

**Architecture:** Novo módulo `b3_core/log.py` centraliza logging JSON; `brapi.py` ganha retry fixo; `ingest.py` usa o novo logger e tem bug de `NameError` corrigido; `app.py` calcula `stale` via FUND_TTL, mantém side-index para fallback sem DB e loga via middleware.

**Tech Stack:** Python stdlib (`json`, `time`, `datetime`, `unittest.mock`), pytest, FastAPI TestClient (httpx), duckdb.

---

## Arquivo de referência

- Spec: `docs/superpowers/specs/2026-03-18-tier1-reliability-design.md`

## Mapa de arquivos

| Ação | Arquivo |
|------|---------|
| Criar | `src/b3_core/log.py` |
| Criar | `tests/conftest.py` |
| Criar | `tests/test_log.py` |
| Criar | `tests/test_brapi_retry.py` |
| Criar | `tests/test_ingest_skipdb.py` |
| Criar | `tests/test_mcp_stale.py` |
| Modificar | `src/b3_etl/brapi.py` |
| Modificar | `src/b3_etl/ingest.py` |
| Modificar | `src/b3_mcp/app.py` |
| Modificar | `requirements-mcp.txt` (adicionar httpx para TestClient) |
| Modificar | `scripts/validate_python.sh` (adicionar `src/b3_core/log.py`) |

---

## Task 0: Infraestrutura de testes

**Files:**
- Create: `tests/conftest.py`
- Modify: `requirements-mcp.txt`

- [ ] **Step 1: Adicionar pytest e httpx às dependências**

```bash
# Adicionar ao final de requirements-mcp.txt:
pytest>=8.0,<9.0
httpx>=0.27,<1.0
```

- [ ] **Step 2: Criar `tests/conftest.py`**

```python
import sys
import os

# garante que src/ está no path para todos os testes
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
```

- [ ] **Step 3: Verificar que pytest encontra o projeto**

```bash
cd /home/paulo/Projetos/b3_llm_report
pip install -r requirements-mcp.txt
pytest tests/ --collect-only
```

Esperado: `no tests ran` (sem erro de importação).

- [ ] **Step 4: Atualizar `scripts/validate_python.sh`**

Adicionar `src/b3_core/log.py` à lista de arquivos verificados. Localizar o bloco `python -m py_compile` e inserir a linha:

```
  src/b3_core/log.py \
```

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py requirements-mcp.txt scripts/validate_python.sh
git commit -m "test: bootstrap pytest infrastructure"
```

---

## Task 1: `b3_core/log.py` — módulo de log compartilhado

**Files:**
- Create: `src/b3_core/log.py`
- Create: `tests/test_log.py`

- [ ] **Step 1: Escrever o teste com falha**

Criar `tests/test_log.py`:

```python
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from b3_core.log import log_info, log_error


def test_log_info_campos_fixos(capsys):
    log_info("test_job", ticker="PETR4")
    captured = capsys.readouterr()
    data = json.loads(captured.out.strip())
    assert data["level"] == "info"
    assert data["job"] == "test_job"
    assert "ts" in data
    assert data["ticker"] == "PETR4"


def test_log_error_campos_fixos(capsys):
    log_error("test_job", error="algo falhou")
    captured = capsys.readouterr()
    data = json.loads(captured.out.strip())
    assert data["level"] == "error"
    assert data["job"] == "test_job"
    assert data["error"] == "algo falhou"


def test_log_info_sem_campos_extras(capsys):
    log_info("job_simples")
    captured = capsys.readouterr()
    data = json.loads(captured.out.strip())
    assert data["level"] == "info"
    assert data["job"] == "job_simples"
    assert "ts" in data
```

- [ ] **Step 2: Rodar para confirmar falha**

```bash
pytest tests/test_log.py -v
```

Esperado: `ImportError: cannot import name 'log_info' from 'b3_core.log'`

- [ ] **Step 3: Implementar `src/b3_core/log.py`**

```python
import json
import sys
from datetime import datetime


def _emit(level: str, job: str, **fields) -> None:
    payload = {
        "level": level,
        "job": job,
        "ts": datetime.utcnow().isoformat() + "Z",
    }
    payload.update(fields)
    print(json.dumps(payload, ensure_ascii=False), file=sys.stdout)


def log_info(job: str, **fields) -> None:
    _emit("info", job, **fields)


def log_error(job: str, **fields) -> None:
    _emit("error", job, **fields)
```

- [ ] **Step 4: Rodar para confirmar aprovação**

```bash
pytest tests/test_log.py -v
```

Esperado: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add src/b3_core/log.py tests/test_log.py
git commit -m "feat: add shared b3_core/log module with log_info/log_error"
```

---

## Task 2: `brapi.py` — retry fixo 3x com delay 2s

**Files:**
- Modify: `src/b3_etl/brapi.py`
- Create: `tests/test_brapi_retry.py`

- [ ] **Step 1: Escrever o teste com falha**

Criar `tests/test_brapi_retry.py`:

```python
import pytest
from unittest.mock import patch, MagicMock, call
import json

from b3_etl.brapi import fetch_quote, BrapiError


def _make_valid_response(ticker="PETR4"):
    body = json.dumps({"results": [{"shortName": ticker}]}).encode()
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = body
    return mock_resp


def test_retry_esgota_3_tentativas_e_levanta_brapi_error():
    with patch("b3_etl.brapi.urllib.request.urlopen", side_effect=OSError("timeout")) as mock_open, \
         patch("b3_etl.brapi.time.sleep") as mock_sleep:
        with pytest.raises(BrapiError):
            fetch_quote("PETR4", [], "https://brapi.dev/api", "")
        assert mock_open.call_count == 3
        assert mock_sleep.call_count == 2  # sleep entre tentativas, não após a última


def test_retry_sucede_na_segunda_tentativa():
    valid = _make_valid_response()
    with patch("b3_etl.brapi.urllib.request.urlopen",
               side_effect=[OSError("timeout"), valid]) as mock_open, \
         patch("b3_etl.brapi.time.sleep"):
        result = fetch_quote("PETR4", [], "https://brapi.dev/api", "")
    assert mock_open.call_count == 2
    assert "results" in result


def test_schema_invalido_nao_faz_retry():
    body = json.dumps({"erro": "not found"}).encode()
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = body
    with patch("b3_etl.brapi.urllib.request.urlopen", return_value=mock_resp) as mock_open, \
         patch("b3_etl.brapi.time.sleep") as mock_sleep:
        with pytest.raises(BrapiError):
            fetch_quote("PETR4", [], "https://brapi.dev/api", "")
    assert mock_open.call_count == 1  # sem retry
    mock_sleep.assert_not_called()
```

- [ ] **Step 2: Rodar para confirmar falha**

```bash
pytest tests/test_brapi_retry.py -v
```

Esperado: `FAILED` — `mock_open.call_count == 1` em vez de 3.

- [ ] **Step 3: Modificar `src/b3_etl/brapi.py`**

Adicionar `import time` e reescrever `fetch_quote`:

```python
import json
import time
import urllib.parse
import urllib.request


class BrapiError(Exception):
    pass


def _build_url(base_url: str, ticker: str, modules: list[str], token: str) -> str:
    base = base_url.rstrip("/")
    params = {}
    if modules:
        params["modules"] = ",".join(modules)
    if token:
        params["token"] = token
    query = urllib.parse.urlencode(params)
    return f"{base}/quote/{ticker}?{query}"


def fetch_quote(
    ticker: str,
    modules: list[str],
    base_url: str,
    token: str,
    timeout: int = 30,
) -> dict:
    url = _build_url(base_url, ticker, modules, token)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "b3-llm-report/etl",
            "Accept": "application/json",
        },
        method="GET",
    )
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                payload = response.read().decode("utf-8")
            data = json.loads(payload)
            break
        except Exception as exc:
            if attempt < max_attempts - 1:
                time.sleep(2)
            else:
                raise BrapiError(f"Falha ao consultar BRAPI para {ticker}: {exc}") from exc

    if not isinstance(data, dict) or "results" not in data:
        raise BrapiError(f"Resposta BRAPI invalida para {ticker}")
    return data
```

- [ ] **Step 4: Rodar para confirmar aprovação**

```bash
pytest tests/test_brapi_retry.py -v
```

Esperado: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add src/b3_etl/brapi.py tests/test_brapi_retry.py
git commit -m "feat: add 3-attempt fixed retry to brapi fetch_quote"
```

---

## Task 3: `ingest.py` — fix NameError + novo logger

**Files:**
- Modify: `src/b3_etl/ingest.py`
- Create: `tests/test_ingest_skipdb.py`

- [ ] **Step 1: Escrever o teste com falha**

Criar `tests/test_ingest_skipdb.py`:

```python
import json
from unittest.mock import patch, MagicMock

from b3_etl.ingest import run_ingest
from b3_core.config import load_config


def _mock_brapi_response(ticker="PETR4"):
    return {
        "results": [{
            "shortName": ticker,
            "currency": "BRL",
            "regularMarketPrice": 35.0,
            "regularMarketTime": 1700000000,
            "regularMarketOpen": 34.5,
            "regularMarketDayHigh": 35.5,
            "regularMarketDayLow": 34.0,
            "regularMarketVolume": 1000000,
            "financialData": {"totalRevenue": 1000000.0},
        }]
    }


def test_skip_db_nao_levanta_name_error(tmp_path, capsys):
    config = load_config()
    config = config.__class__(
        **{**config.__dict__, "raw_dir": str(tmp_path / "raw")}
    )
    with patch("b3_etl.ingest.fetch_quote", return_value=_mock_brapi_response()):
        result = run_ingest(
            tickers=["PETR4"],
            config=config,
            modules=["financialData"],
            write_snapshot=False,
            skip_db=True,
        )
    assert result == 0


def test_log_json_emitido_no_sucesso(tmp_path, capsys):
    config = load_config()
    config = config.__class__(
        **{**config.__dict__, "raw_dir": str(tmp_path / "raw")}
    )
    with patch("b3_etl.ingest.fetch_quote", return_value=_mock_brapi_response()):
        run_ingest(
            tickers=["PETR4"],
            config=config,
            modules=["financialData"],
            write_snapshot=False,
            skip_db=True,
        )
    lines = [l for l in capsys.readouterr().out.strip().splitlines() if l]
    logs = [json.loads(l) for l in lines]
    jobs = [l["job"] for l in logs]
    assert "etl_start" in jobs
    ticker_logs = [l for l in logs if l.get("job") == "etl_ticker"]
    assert len(ticker_logs) == 1
    assert ticker_logs[0]["ticker"] == "PETR4"
    assert "rows_fundamentals" in ticker_logs[0]
    assert ticker_logs[0]["rows_prices"] == 0  # skip_db=True, nenhum preço gravado no DB
    assert "duration_ms" in ticker_logs[0]
```

- [ ] **Step 2: Rodar para confirmar falha**

```bash
pytest tests/test_ingest_skipdb.py -v
```

Esperado: `FAILED` — `NameError: name 'fundamentals_records' is not defined` no primeiro teste.

- [ ] **Step 3: Modificar `src/b3_etl/ingest.py`**

**3a.** Substituir `from b3_etl.brapi import fetch_quote, BrapiError` pelo mesmo import (sem mudança) e adicionar o import do novo logger logo após:

```python
# substituir bloco de imports no topo:
import hashlib
import json
import os
import time
from datetime import datetime, date
from typing import Any, Optional

from b3_core.config import Config
from b3_core.log import log_info, log_error
from b3_storage.db import connect, missing_tables, table_exists
from b3_etl.brapi import fetch_quote, BrapiError
```

**3b.** Remover as funções `_utc_now()` e `_log()` do arquivo (linhas 12–23 do arquivo atual). `_utc_now()` era usada apenas por `_log()`, mas atenção: `run_ingest` abre com `fetched_at = _utc_now()` — substituir essa linha por:

```python
fetched_at = datetime.utcnow()
```

`datetime` já está nos imports (Step 3a).

**3c.** Em `run_ingest`, logo antes do loop `for ticker in tickers:`, adicionar:

```python
    log_info("etl_start", tickers=tickers, modules=modules)
```

**3d.** Inicializar `fundamentals_records`, `rows_prices` e `ticker_start` **antes** da guarda `if not results: continue`. A ordem exata no loop deve ser:

```python
        # (1) fetch já ocorreu acima; results = data.get("results") or []
        fundamentals_records: list[dict] = []
        rows_prices = 0
        ticker_start = time.time()

        if not results:
            log_error("etl_ticker", ticker=ticker, error="resposta BRAPI sem resultados")
            continue
        # (2) só então: payload = results[0]
```

Isso garante que `ticker_start` e `fundamentals_records` existam mesmo que o loop chegue ao `continue` por ausência de resultados, evitando `NameError` em caminhos de erro futuros.

**3e.** Dentro do bloco `if con and not missing:`, após a inserção de preços (o `_delete_then_insert` de prices), adicionar:

```python
                rows_prices = 1
```

**3f.** Substituir o `_log` final do loop (linha 338–344 do original) por:

```python
        log_info(
            "etl_ticker",
            ticker=ticker,
            rows_fundamentals=len(fundamentals_records),
            rows_prices=rows_prices,
            duration_ms=int((time.time() - ticker_start) * 1000),
        )
```

**3g.** Substituir os dois `_log("erro", ...)` do loop pelos equivalentes:

```python
# na captura de BrapiError:
        except BrapiError as exc:
            log_error("etl_ticker", ticker=ticker, error=str(exc))
            continue

# no ROLLBACK:
                log_error("etl_ticker", ticker=ticker, error=str(exc))
```

**3h.** Substituir o `_log` do snapshot:

```python
        log_info("etl_snapshot", date=snapshot_date, dest=config.snapshot_dir)
```

**3i.** Substituir o `_log("erro", "Tabelas ausentes ...")`:

```python
            log_error("etl_start", error="tabelas ausentes", tabelas=missing)
```

**3j.** Substituir o `_log("erro", "Nenhum ticker ...")`:

```python
        log_error("etl_start", error="nenhum ticker informado")
```

**3k.** Substituir o `_log("erro", "Resposta BRAPI sem resultados ...")`:

```python
            log_error("etl_ticker", ticker=ticker, error="resposta BRAPI sem resultados")
```

- [ ] **Step 4: Rodar para confirmar aprovação**

```bash
pytest tests/test_ingest_skipdb.py -v
```

Esperado: `2 passed`

- [ ] **Step 5: Validação sintática geral**

```bash
bash scripts/validate_python.sh
```

Esperado: sem output (todos os arquivos compilam).

- [ ] **Step 6: Commit**

```bash
git add src/b3_etl/ingest.py tests/test_ingest_skipdb.py
git commit -m "fix: initialize fundamentals_records before DB block; use b3_core/log in ETL"
```

---

## Task 4: `app.py` — stale threshold + fallback degradado + middleware de log

**Files:**
- Modify: `src/b3_mcp/app.py`
- Create: `tests/test_mcp_stale.py`

- [ ] **Step 1: Escrever os testes com falha**

Criar `tests/test_mcp_stale.py`:

```python
# IMPORTANTE: conftest.py adiciona src/ ao sys.path.
# Todos os imports e patches usam b3_mcp.app (sem prefixo src.)
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta
from fastapi.testclient import TestClient

from b3_mcp.app import app


def _auth_headers():
    return {"Authorization": "Bearer test-token"}


@pytest.fixture(autouse=True)
def set_auth_token(monkeypatch):
    monkeypatch.setenv("AUTH_TOKEN", "test-token")


def _fake_meta(last_update: datetime | None):
    return {
        "name": "Petrobras",
        "sector": "Energy",
        "industry": "Oil",
        "last_update": last_update,
        "last_update_str": last_update.isoformat() if last_update else None,
        "source": "brapi.dev",
    }


def _fake_con():
    con = MagicMock()
    con.execute.return_value.fetchone.return_value = [None]
    con.execute.return_value.fetchall.return_value = []
    return con


def test_stale_false_quando_last_update_recente():
    recent = datetime.utcnow() - timedelta(hours=1)
    with patch("b3_mcp.app.os.path.exists", return_value=True), \
         patch("b3_mcp.app.connect", return_value=_fake_con()), \
         patch("b3_mcp.app.missing_tables", return_value=[]), \
         patch("b3_mcp.app._company_metadata", return_value=_fake_meta(recent)), \
         patch("b3_mcp.app._latest_period", return_value=None), \
         patch("b3_mcp.app._latest_price", return_value=None), \
         patch("b3_mcp.app.config") as mock_config:
        mock_config.auth_token = "test-token"
        mock_config.fund_ttl = 86400
        mock_config.price_ttl = 900
        mock_config.db_path = "/fake/path.duckdb"
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/v1/fundamentals/PETR4", headers=_auth_headers())

    assert response.status_code == 200
    assert response.json()["metadata"]["stale"] is False


def test_stale_true_quando_last_update_antigo():
    old = datetime.utcnow() - timedelta(hours=30)
    with patch("b3_mcp.app.os.path.exists", return_value=True), \
         patch("b3_mcp.app.connect", return_value=_fake_con()), \
         patch("b3_mcp.app.missing_tables", return_value=[]), \
         patch("b3_mcp.app._company_metadata", return_value=_fake_meta(old)), \
         patch("b3_mcp.app._latest_period", return_value=None), \
         patch("b3_mcp.app._latest_price", return_value=None), \
         patch("b3_mcp.app.config") as mock_config:
        mock_config.auth_token = "test-token"
        mock_config.fund_ttl = 86400
        mock_config.price_ttl = 900
        mock_config.db_path = "/fake/path.duckdb"
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/v1/fundamentals/PETR4", headers=_auth_headers())

    assert response.status_code == 200
    assert response.json()["metadata"]["stale"] is True


def test_stale_true_quando_nenhum_dado():
    with patch("b3_mcp.app.os.path.exists", return_value=True), \
         patch("b3_mcp.app.connect", return_value=_fake_con()), \
         patch("b3_mcp.app.missing_tables", return_value=[]), \
         patch("b3_mcp.app._company_metadata", return_value=_fake_meta(None)), \
         patch("b3_mcp.app._latest_period", return_value=None), \
         patch("b3_mcp.app._latest_price", return_value=None), \
         patch("b3_mcp.app.config") as mock_config:
        mock_config.auth_token = "test-token"
        mock_config.fund_ttl = 86400
        mock_config.price_ttl = 900
        mock_config.db_path = "/fake/path.duckdb"
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/v1/fundamentals/PETR4", headers=_auth_headers())

    assert response.status_code == 200
    assert response.json()["metadata"]["stale"] is True
```

- [ ] **Step 2: Rodar para confirmar falha**

```bash
pytest tests/test_mcp_stale.py -v
```

Esperado: `FAILED` — stale calculado incorretamente (apenas verifica `None`, não threshold).

- [ ] **Step 3: Modificar `src/b3_mcp/app.py`**

**3a.** Adicionar imports no topo:

```python
import time
from datetime import datetime, date, timedelta
# (substituir a linha existente: from datetime import datetime, date)
```

```python
from b3_core.log import log_info, log_error
# adicionar após os imports existentes de b3_*
```

**3b.** Adicionar side-index e helper de stale após `cache = TTLCache()`:

```python
# índice lateral: ticker → última cache_key de fundamentals
_ticker_fund_key: dict[str, str] = {}


def _is_stale(last_update, fund_ttl: int) -> bool:
    if last_update is None:
        return True
    now = datetime.utcnow()
    return (now - last_update) > timedelta(seconds=fund_ttl)
```

**3c.** Adicionar middleware de log logo após a definição do `app`:

```python
@app.middleware("http")
async def log_requests(request, call_next):
    start = time.time()
    response = await call_next(request)
    log_info(
        "mcp_request",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=int((time.time() - start) * 1000),
    )
    return response
```

**3d.** Em `_company_metadata`, retornar o `datetime` bruto no dict (para uso no cálculo de stale):

```python
def _company_metadata(con, ticker: str) -> dict:
    query = """
        SELECT name, sector, industry, last_update, source
        FROM companies
        WHERE ticker = ?
        LIMIT 1
    """
    row = con.execute(query, [ticker]).fetchone()
    if not row:
        return {}
    return {
        "name": row[0],
        "sector": row[1],
        "industry": row[2],
        "last_update": row[3],          # datetime bruto para cálculo de stale
        "last_update_str": row[3].isoformat() if row[3] else None,  # string para resposta
        "source": row[4],
    }
```

**3e.** Modificar o endpoint `/v1/fundamentals` para:
- Usar `_is_stale(meta.get("last_update"), config.fund_ttl)` em vez de `last_update is None`
- Usar `meta.get("last_update_str")` para o campo `last_update` na resposta
- Atualizar o side-index `_ticker_fund_key[ticker] = cache_key` após `cache.set`
- Adicionar fallback quando DB está inacessível

Substituir o corpo do endpoint `fundamentals` pela versão abaixo:

```python
@app.get("/v1/fundamentals/{ticker}")
def fundamentals(
    ticker: str,
    as_of: Optional[str] = Query(default=None),
    modules: Optional[str] = Query(default=None),
    authorization: Optional[str] = Header(default=None),
) -> dict:
    _require_auth(authorization)
    as_of_date = _parse_date(as_of)
    module_list = [m.strip() for m in (modules or "snapshot,income,balance,ratios").split(",") if m.strip()]

    # fallback degradado: se DB inacessível, tenta servir cache stale
    if not os.path.exists(config.db_path):
        fallback_key = _ticker_fund_key.get(ticker)
        if fallback_key:
            cached = cache.get(fallback_key)
            if cached:
                result = dict(cached)
                result["metadata"] = dict(result.get("metadata", {}))
                result["metadata"]["stale"] = True
                return result
        raise HTTPException(status_code=503, detail="DuckDB indisponivel e sem cache.")

    con = _get_db()
    meta = _company_metadata(con, ticker)
    last_update = meta.get("last_update")        # datetime bruto
    last_update_str = meta.get("last_update_str")  # string para resposta

    cache_key = f"fund:{ticker}:{last_update_str}:{as_of}:{','.join(module_list)}"
    cached = cache.get(cache_key)
    if cached:
        con.close()
        return cached

    snapshot = {}
    income = {}
    balance = {}
    ratios = {}
    partial = False

    if "snapshot" in module_list:
        period = _latest_period(con, ticker, "snapshot", as_of_date)
        snapshot = _load_kv(con, ticker, "snapshot", period)
        if not snapshot:
            partial = True
    if "income" in module_list:
        period = _latest_period(con, ticker, "income", as_of_date)
        income = _load_kv(con, ticker, "income", period)
        if not income:
            partial = True
    if "balance" in module_list:
        period = _latest_period(con, ticker, "balance", as_of_date)
        balance = _load_kv(con, ticker, "balance", period)
        if not balance:
            partial = True
    if "ratios" in module_list and table_exists(con, "ratios"):
        if as_of_date:
            query = """
                SELECT ratio_name, value
                FROM (
                    SELECT ratio_name, value,
                        ROW_NUMBER() OVER (PARTITION BY ratio_name ORDER BY period DESC) AS rn
                    FROM ratios
                    WHERE ticker = ? AND period <= ?
                )
                WHERE rn = 1
            """
            rows = con.execute(query, [ticker, as_of_date]).fetchall()
        else:
            query = """
                SELECT ratio_name, value
                FROM (
                    SELECT ratio_name, value,
                        ROW_NUMBER() OVER (PARTITION BY ratio_name ORDER BY period DESC) AS rn
                    FROM ratios
                    WHERE ticker = ?
                )
                WHERE rn = 1
            """
            rows = con.execute(query, [ticker]).fetchall()
        ratios = {name: value for name, value in rows}
        if not ratios:
            partial = True

    price = _latest_price(con, ticker, as_of_date)
    if not price:
        partial = True

    response = {
        "ticker": ticker,
        "as_of": as_of_date.isoformat() if as_of_date else None,
        "snapshot": snapshot if "snapshot" in module_list else {},
        "income": income if "income" in module_list else {},
        "balance": balance if "balance" in module_list else {},
        "ratios": ratios if "ratios" in module_list else {},
        "price": price,
        "metadata": {
            "last_update": last_update_str,
            "stale": _is_stale(last_update, config.fund_ttl),
            "partial": partial,
            "source": meta.get("source"),
            "name": meta.get("name"),
            "sector": meta.get("sector"),
            "industry": meta.get("industry"),
        },
    }

    cache.set(cache_key, response, config.fund_ttl)
    _ticker_fund_key[ticker] = cache_key
    con.close()
    return response
```

- [ ] **Step 4: Rodar para confirmar aprovação**

```bash
pytest tests/test_mcp_stale.py -v
```

Esperado: `3 passed`

- [ ] **Step 5: Rodar todos os testes**

```bash
pytest tests/ -v
```

Esperado: todos `passed`, nenhum `ERROR`.

- [ ] **Step 6: Validação sintática**

```bash
bash scripts/validate_python.sh
```

Esperado: sem output.

- [ ] **Step 7: Commit**

```bash
git add src/b3_mcp/app.py tests/test_mcp_stale.py
git commit -m "feat: stale threshold via FUND_TTL, degraded DB fallback, request logging middleware"
```

---

## Critérios de aceitação (do spec)

- [ ] `bash scripts/validate_python.sh` — sem erros
- [ ] `pytest tests/ -v` — todos os testes passam
- [ ] `python ingest.py --tickers PETR4 --skip-db` — sem `NameError`, emite JSON com campos `level`, `job`, `ts`, `ticker`
- [ ] Com `FUND_TTL=1`: esperar 2s, `/v1/fundamentals/PETR4` retorna `stale: true`
- [ ] Com DB ausente e cache populado: retorna HTTP 200 com `stale: true`
- [ ] Com DB ausente e cache vazio: retorna HTTP 503
