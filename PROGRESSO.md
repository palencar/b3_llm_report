# Progresso do Projeto

Este documento registra as tarefas acordadas e o andamento da reorganização do projeto.

## Tarefas

### 1) Diagnóstico do código atual e mapeamento do fluxo
- Status: concluída
- Saída:
  - Fluxo atual mapeado.
  - Pontos de acoplamento identificados.
  - Regras de compatibilidade registradas.
  - Detalhes:
    - Entrada principal: `main.py` recebe `<TICKER>` via CLI, carrega `.env`, chama `yfinance` + `crawl4ai`, monta prompt e chama LLM via `OpenAI` (Ollama compatível), salvando em `reports/<TICKER>.md`.
    - Dependências críticas: `OPENAI_*` e `CRAWL4AI_*` via env vars.
    - Prompt em `prepare_request.py` define formato da resposta e deve ser preservado para compatibilidade.
    - `get_info_yfinance.py` retorna JSON e texto formatado; `get_info_crawl4ai.py` faz scraping via LLMExtractionStrategy e retorna texto formatado.

### 2) Definir arquitetura alvo e layout de pastas
- Status: concluída
- Saída esperada:
  - Árvore de pastas proposta.
  - Regras de import entre módulos.
  - Pontos de entrada preservados (`main.py`).

### 3) Centralizar configuração por variáveis de ambiente
- Status: concluída
- Saída esperada:
  - Lista oficial de env vars e defaults.
  - Módulo `config`.
  - Detalhes:
    - Módulo alvo: `src/b3_core/config.py` (compartilhado por `b3_report`, `b3_etl` e `b3_mcp`).
    - Variáveis (com defaults propostos):
      - `OPENAI_API_KEY` (default: `api_key` para Ollama local)
      - `OPENAI_URL_BASE` (default: `http://localhost:11434/v1`)
      - `OPENAI_MODEL_NAME` (default: `llama3.1`)
      - `CRAWL4AI_MODEL_API_KEY` (default: `token`)
      - `CRAWL4AI_MODEL_PROVIDER` (default: `ollama/llama3.1:8b-8k`)
      - `CRAWL4AI_MODEL_URL_BASE` (default: `http://localhost:11434`)
      - `DB_PATH` (default: `data/duckdb/b3_fundamentals.duckdb`)
      - `SNAPSHOT_DIR` (default: `data/snapshots`)
      - `RAW_DIR` (default: `data/raw`)
      - `BRAPI_KEY` (default: vazio; obrigatório para ETL)
      - `BRAPI_BASE_URL` (default: `https://brapi.dev/api`)
      - `AUTH_TOKEN` (default: vazio; obrigatório no MCP)
      - `CACHE_TYPE` (default: `memory`)
      - `FUND_TTL` (default: `86400`)
      - `PRICE_TTL` (default: `900`)
      - `LOG_LEVEL` (default: `INFO`)

### 4) Modelar storage e esquema DuckDB
- Status: concluída
- Saída esperada:
  - Esquema documentado (tabelas + chaves).
  - Funções de criação/migração.
  - Detalhes:
    - Arquivo principal: `data/duckdb/b3_fundamentals.duckdb`.
    - Snapshots: `data/snapshots/YYYYMMDD/*.parquet`.
    - Raw files: `data/raw/<source>/...` com registro em tabela.
    - Tabelas mínimas propostas (DDL lógico):
      - `companies(ticker TEXT PK, name TEXT, sector TEXT, industry TEXT, last_update TIMESTAMP, source TEXT, updated_at TIMESTAMP)`
      - `fundamentals(ticker TEXT, period DATE, statement_type TEXT, key TEXT, value DOUBLE, currency TEXT, source TEXT, fetched_at TIMESTAMP, PRIMARY KEY(ticker, period, statement_type, key))`
      - `prices(ticker TEXT, ts TIMESTAMP, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume BIGINT, source TEXT, PRIMARY KEY(ticker, ts))`
      - `ratios(ticker TEXT, period DATE, ratio_name TEXT, value DOUBLE, computed_at TIMESTAMP, PRIMARY KEY(ticker, period, ratio_name))`
      - `raw_files(source TEXT, path TEXT, fetched_at TIMESTAMP, checksum TEXT, size_bytes BIGINT, PRIMARY KEY(source, path))`
    - Estratégia de idempotência: `INSERT ... ON CONFLICT DO UPDATE` por PK.

### 5) Implementar ETL MVP BRAPI
- Status: concluída
- Saída esperada:
  - `ingest.py` funcional com ingestão BRAPI.
  - DuckDB e snapshots Parquet gerados.
  - Detalhes:
    - Implementado pacote `src/b3_etl` com fetch BRAPI via stdlib (`urllib`).
    - Criado CLI `ingest.py` com flags `--tickers`, `--modules`, `--skip-db`, `--skip-snapshot`.
    - Persistencia no DuckDB depende do schema existente; em falta, o ETL registra erro e segue apenas com raw files.
    - Raw JSON salvo em `data/raw/brapi/<TICKER>/`.
    - Snapshots Parquet por data em `data/snapshots/YYYYMMDD/`.
    - Dependencia isolada em `requirements-etl.txt` (`duckdb`).

### 6) Implementar MCP/Skill MVP
- Status: concluída
- Saída esperada:
  - `mcp_server.py` com endpoints MVP.
  - Cache in-memory e auth por token.
  - Detalhes:
    - Criado `src/b3_mcp/app.py` com FastAPI e endpoints `/v1/fundamentals`, `/v1/prices`, `/v1/health`, `/v1/search`, `/v1/metadata`.
    - Auth obrigatoria via `Authorization: Bearer <token>` (usa `AUTH_TOKEN`).
    - Cache in-memory simples em `src/b3_mcp/cache.py` com TTL.
    - Dependencias isoladas em `requirements-mcp.txt`.
    - Wrapper `mcp_server.py` exposto para execucao via uvicorn.

### 7) Reorganizar o pipeline atual de relatório
- Status: concluída
- Saída esperada:
  - CLI `python main.py <TICKER>` continua funcionando.
  - Funções movidas para módulos.
  - Detalhes:
    - Criado pacote `src/b3_report` com módulos `cli.py`, `llm.py`, `prompts.py` e `sources/`.
    - `main.py` agora é um wrapper fino que chama `b3_report.cli.run_report`.
    - `prepare_request.py`, `get_info_yfinance.py` e `get_info_crawl4ai.py` foram mantidos como fachadas de compatibilidade para evitar quebra de imports.
    - O relatório continua sendo salvo em `reports/<TICKER>.md`.
    - Validação sintática executada com `python -m py_compile`.

### 8) Validação e documentação
- Status: concluída
- Saída esperada:
  - Scripts de demo e validação.
  - README atualizado.
  - Detalhes:
    - `init_db.py` implementado: executa `SCHEMA_SQL` via `b3_storage.schema` e cria as 5 tabelas no DuckDB.
    - `.env.example` criado com todas as variáveis e defaults documentados.
    - Scripts de demo em `scripts/`: `demo_init_db.sh`, `demo_ingest.sh`, `demo_run_server.sh`, `demo_query.sh`, `demo_report.sh`.
    - `scripts/validate_python.sh` valida sintaxe de todos os módulos Python.
    - README atualizado com todos os fluxos, variáveis de ambiente e limitações.
