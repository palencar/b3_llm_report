# Design — Tier 1: Confiabilidade do ETL e MCP

**Data:** 2026-03-18
**Escopo:** 4 melhorias de confiabilidade sobre a base MVP existente

---

## Contexto

O MVP (tarefas 1–8) entregou ETL BRAPI, MCP FastAPI, storage DuckDB e pipeline de relatório funcionais.
Este spec cobre o Tier 1 de melhorias identificadas: logging padronizado, retry no ETL, campo `stale` correto e fallback degradado no MCP.

---

## Itens

### A — `companies.last_update` + cache key baseada em `last_update`

**Estado atual:** já implementado no MVP.
- ETL grava `last_update = fetched_at` na tabela `companies` ao fim de cada ticker.
- Cache key do MCP já usa `last_update` como versão: `fund:{ticker}:{last_update}:{as_of}:{modules}`.

**Ação:** nenhuma mudança necessária neste item.

---

### B — Campo `stale` e fallback degradado no MCP

**Estado atual:**
- `stale` é `True` apenas quando `last_update is None`.
- `_get_db()` retorna 503 imediatamente se o DB não existe — sem tentativa de servir cache.

**Design:**

**Stale threshold:**
- `stale = True` quando `last_update is None` **ou** `now - last_update > FUND_TTL`.
- `FUND_TTL` vem de `config.fund_ttl` (env var, default 86400s / 24h).
- Aplicado apenas em `/v1/fundamentals`.

**Fallback degradado:**
- Quando DB inacessível, `/v1/fundamentals` tenta retornar a última entrada em cache com `stale: true`, HTTP 200.
- Se não houver cache: retorna 503 com mensagem explicativa.
- `/v1/prices`, `/v1/search`, `/v1/metadata`: mantêm comportamento atual (503 imediato), pois dados stale de preços e metadados não são úteis.

**Mecanismo de lookup no fallback:**
O cache key inclui `last_update` (obtido do DB), que não está disponível quando o DB está inacessível. A solução é manter um índice lateral em `app.py`:

```python
_ticker_fund_key: dict[str, str] = {}  # ticker → última cache_key usada
```

Sempre que `cache.set(cache_key, response, ttl)` é chamado em `/v1/fundamentals`, também se faz `_ticker_fund_key[ticker] = cache_key`. No fallback, lookup via `_ticker_fund_key.get(ticker)` seguido de `cache.get(chave)`. `cache.py` não é alterado.

**Stale threshold — timezone:**
Comparação usa `datetime.utcnow()` (naive UTC) em ambos os lados. O `last_update` é lido diretamente do row do DuckDB (tipo `datetime`, naive UTC) — não do campo string da resposta cacheada. Exemplo:

```python
from datetime import datetime, timedelta
now = datetime.utcnow()
stale = last_update is None or (now - last_update) > timedelta(seconds=config.fund_ttl)
```

Nota: `_company_metadata()` já converte `last_update` para string via `.isoformat()`. Para o cálculo de stale, o `last_update` deve ser lido como `datetime` diretamente do row do DuckDB — não via `meta.get("last_update")`. A implementação deve fazer uma query separada ou modificar `_company_metadata()` para retornar o `datetime` bruto junto com os demais campos.

**Arquivos alterados:** `src/b3_mcp/app.py`

---

### C — Retry fixo no fetch BRAPI

**Estado atual:** falha imediata com `BrapiError` na primeira exceção de rede.

**Design:**
- 3 tentativas totais com `time.sleep(2)` entre elas.
- Na 3ª falha consecutiva, propaga `BrapiError` normalmente.
- Retry somente para exceções de rede/timeout (qualquer `Exception` no `urlopen`).
- Resposta com schema inválido (`"results" not in data`) não faz retry — é erro de contrato.
- Sleep fixo é intencional para manter simplicidade; sem backoff exponencial ou retry assíncrono neste escopo.

**Arquivos alterados:** `src/b3_etl/brapi.py`

---

### D — Módulo de log compartilhado + logs padronizados

**Design do módulo `src/b3_core/log.py`:**

```
log_info(job: str, **fields) -> None
log_error(job: str, **fields) -> None
```

- Emitem JSON para stdout.
- Campos fixos: `level` (`"info"` / `"error"`), `job`, `ts` (ISO UTC).
- Campos extras via `**fields` (ex: `ticker`, `rows_out`, `duration_ms`, `error`).
- Sem dependências externas.

**ETL — `src/b3_etl/ingest.py`:**
- Remove função `_log()` local.
- Usa `log_info` / `log_error` de `b3_core.log`.
- Eventos e campos:
  - `job="etl_start"`: `tickers`, `modules`
  - `job="etl_ticker"` (sucesso): `ticker`, `rows_fundamentals`, `rows_prices`, `duration_ms`
  - `job="etl_ticker"` (erro): `ticker`, `error`
  - `job="etl_snapshot"`: `date`, `dest`
- **Bug fix:** `fundamentals_records = []` inicializado antes do bloco `if con and not missing`, evitando `NameError` quando `--skip-db` é passado.
- **Log de sucesso por ticker** (substitui o `_log` atual na linha 338):
  - `job="etl_ticker"`, `ticker`, `rows_fundamentals` (len de `fundamentals_records`), `rows_prices` (1 se price_ts válido, 0 caso contrário), `duration_ms` (tempo desde início do ticker)

**MCP — `src/b3_mcp/app.py`:**
- Middleware FastAPI `@app.middleware("http")` loga cada request:
  - `job="mcp_request"`: `method`, `path`, `status_code`, `duration_ms`
- Usa `log_info` / `log_error` de `b3_core.log`.

---

## Arquivos afetados

| Arquivo | Ação |
|---------|------|
| `src/b3_core/log.py` | Criar |
| `src/b3_etl/brapi.py` | Editar — adicionar retry |
| `src/b3_etl/ingest.py` | Editar — novo logger, fix bug `fundamentals_records` |
| `src/b3_mcp/app.py` | Editar — stale threshold, fallback degradado, middleware de log |

---

## O que não muda

- Interface pública dos endpoints (sem quebra de contrato).
- Schema DuckDB.
- `src/b3_mcp/cache.py` — sem alterações.
- `src/b3_core/config.py` — sem novas variáveis (`FUND_TTL` já existe).
- Wrappers `ingest.py`, `mcp_server.py`, `main.py`.

---

## Critérios de aceitação

1. `python -m py_compile` passa em todos os arquivos alterados.
2. `python init_db.py && python ingest.py --tickers PETR4 --skip-snapshot` emite JSON de log com campos `level`, `job`, `ts`, `ticker`.
3. `python ingest.py --tickers PETR4 --skip-db` não levanta `NameError`.
4. Com DB presente e `last_update` há mais de `FUND_TTL` segundos: `/v1/fundamentals/PETR4` retorna `stale: true`.
5. Com DB ausente e cache populado: `/v1/fundamentals/PETR4` retorna HTTP 200 com `stale: true`.
6. Com DB ausente e cache vazio: `/v1/fundamentals/PETR4` retorna HTTP 503.
