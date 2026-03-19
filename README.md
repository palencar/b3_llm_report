# b3_llm_report

Projeto experimental para análise de ações da B3 com três frentes complementares:

- pipeline de relatório com `yfinance` + Fundamentus via `crawl4ai` + LLM local compatível com OpenAI/Ollama;
- ETL MVP para ingestão BRAPI em DuckDB + snapshots Parquet;
- servidor MCP read-only para expor os dados locais a agentes em sandbox.

## Estrutura atual

- `main.py`: wrapper do pipeline de relatório legado.
- `init_db.py`: inicializa o schema DuckDB local.
- `ingest.py`: ETL MVP BRAPI.
- `mcp_server.py`: wrapper do servidor MCP.
- `src/b3_report/`: pipeline de relatório.
- `src/b3_etl/`: ingestão BRAPI.
- `src/b3_storage/`: schema e acesso ao DuckDB.
- `src/b3_mcp/`: API FastAPI read-only.
- `scripts/`: scripts de demo e validação.

## Ambiente

Use um ambiente virtual Python:

```bash
python -m venv venv
source venv/bin/activate
```

Instale as dependências conforme o fluxo que será usado:

```bash
pip install -r requirements.txt
pip install -r requirements-etl.txt
pip install -r requirements-mcp.txt
```

## Variáveis de ambiente

As variáveis abaixo são lidas pelo projeto. Quando houver default, ele já está embutido no código.

### Relatório LLM

- `OPENAI_API_KEY` default: `api_key`
- `OPENAI_URL_BASE` default: `http://localhost:11434/v1`
- `OPENAI_MODEL_NAME` default: `llama3.1`
- `CRAWL4AI_MODEL_API_KEY` default: `token`
- `CRAWL4AI_MODEL_PROVIDER` default: `ollama/llama3.1:8b-8k`
- `CRAWL4AI_MODEL_URL_BASE` default: `http://localhost:11434`

### ETL e storage

- `DB_PATH` default: `data/duckdb/b3_fundamentals.duckdb`
- `SNAPSHOT_DIR` default: `data/snapshots`
- `RAW_DIR` default: `data/raw`
- `BRAPI_KEY` default: vazio
- `BRAPI_BASE_URL` default: `https://brapi.dev/api`

### MCP

- `AUTH_TOKEN` default: vazio
- `CACHE_TYPE` default: `memory`
- `FUND_TTL` default: `86400`
- `PRICE_TTL` default: `900`
- `LOG_LEVEL` default: `INFO`

## Fluxos principais

### 1. Gerar relatório com LLM

Pré-requisitos:
- Ollama ou endpoint OpenAI compatível acessível.
- `crawl4ai` configurado para o modelo usado na extração do Fundamentus.

Execução:

```bash
python main.py PETR4
```

Saída:
- relatório em `reports/PETR4.md`

### 2. Inicializar o DuckDB

```bash
python init_db.py
```

Ou:

```bash
bash scripts/demo_init_db.sh
```

### 3. Rodar o ETL MVP BRAPI

Pré-requisito:
- definir `BRAPI_KEY` se a sua conta/plano exigir token.

Execução:

```bash
python ingest.py --tickers PETR4,ITUB4,VALE3
```

Ou:

```bash
bash scripts/demo_ingest.sh PETR4,ITUB4,VALE3
```

Saídas:
- DuckDB em `data/duckdb/`
- raw JSON em `data/raw/brapi/<TICKER>/`
- snapshots Parquet em `data/snapshots/YYYYMMDD/`

Observação:
- o ETL não cria tabelas automaticamente; execute `init_db.py` antes.

### 4. Subir o servidor MCP

Pré-requisito:
- `AUTH_TOKEN` definido.
- DuckDB inicializado.

Execução:

```bash
uvicorn mcp_server:app --host 0.0.0.0 --port 8000
```

Ou:

```bash
bash scripts/demo_run_server.sh
```

Endpoints principais:
- `GET /v1/health`
- `GET /v1/fundamentals/{ticker}`
- `GET /v1/prices/{ticker}`
- `POST /v1/search`
- `GET /v1/metadata/{ticker}`

Consulta de exemplo:

```bash
export AUTH_TOKEN="seu_token"
bash scripts/demo_query.sh PETR4
```

## Validação mínima

Validação sintática dos arquivos Python principais:

```bash
bash scripts/validate_python.sh
```

## Limitações atuais

- O ETL MVP implementado cobre BRAPI. CVM e fallback estruturado para Fundamentus ainda não foram integrados ao storage local.
- O servidor MCP usa cache apenas em memória. Redis ainda não foi implementado.
- O pipeline de relatório continua dependente de chamadas externas em tempo de execução.
- Não há suíte automatizada de testes; a validação atual é sintática e operacional.

## Alerta

Este projeto é experimental e não deve ser usado como recomendação de investimento.
