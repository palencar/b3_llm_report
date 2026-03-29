# Design — Watch Queue: Geração de Relatórios por Fila de Arquivos

**Data:** 2026-03-28
**Escopo:** Script de polling que monitora um diretório de fila e gera relatórios LLM sob demanda, com deduplicação por idade do relatório.

---

## Contexto

O container R detecta alertas sobre símbolos B3 e precisa disparar a geração de relatórios LLM sem acoplamento direto entre os dois processos. A solução usa um diretório compartilhado como fila: R cria arquivos, Python processa e gera relatórios.

---

## Arquivos modificados

| Arquivo | Ação |
|---------|------|
| `watch_queue.py` | Criar — loop de polling + lógica de age check |
| `src/b3_core/config.py` | Modificar — adicionar `queue_dir`, `report_min_age_hours`, `queue_poll_seconds` |
| `.env.example` | Modificar — documentar as 3 novas variáveis |

`main.py`, `src/b3_report/cli.py` e o resto não mudam.

---

## Configuração

Três variáveis novas em `.env` / `Config`:

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `QUEUE_DIR` | `queue` | Diretório monitorado para triggers |
| `REPORT_MIN_AGE_HOURS` | `24` | Mínimo de horas entre relatórios do mesmo ticker |
| `QUEUE_POLL_SECONDS` | `60` | Intervalo entre varreduras da fila |

---

## `watch_queue.py`

### Inicialização

```python
load_dotenv()
config = load_config()
os.makedirs(config.queue_dir, exist_ok=True)
os.makedirs("reports", exist_ok=True)
```

### Loop principal

```python
while True:
    _process_queue(config)
    time.sleep(config.queue_poll_seconds)
```

### `_process_queue(config)`

Para cada arquivo em `config.queue_dir`:

1. Extrai `ticker = os.path.basename(filepath).upper()`
2. Verifica validade: apenas letras e dígitos, comprimento 3-6 — se inválido, log warning e remove
3. Verifica idade do relatório existente:
   - `report_path = os.path.join("reports", f"{ticker}.md")`
   - Se existe e `(now - mtime) < report_min_age_hours` → log "skipped {ticker} (report age: {age:.1f}h)" e remove da fila
4. Caso contrário → chama `run_report(ticker)`, log "generated {ticker}"
5. Qualquer exceção em `run_report` → log error, remove da fila (loop não trava)
6. Remove arquivo da fila após processamento (sucesso, skip ou erro)

### Invariante

O arquivo da fila é **sempre removido** após ser processado. A deduplicação é controlada pela idade do relatório em `reports/`, não pela presença do arquivo na fila. Quatro alertas para o mesmo ticker no mesmo dia produzem um único arquivo na fila (R usa `file.create` que é idempotente) e um único relatório.

---

## Modificação em `src/b3_core/config.py`

```python
# Novos campos no dataclass Config:
queue_dir: str
report_min_age_hours: float
queue_poll_seconds: int

# Em load_config():
queue_dir=_get_env("QUEUE_DIR", "queue"),
report_min_age_hours=float(_get_env("REPORT_MIN_AGE_HOURS", "24")),
queue_poll_seconds=int(_get_env("QUEUE_POLL_SECONDS", "60")),
```

---

## Tratamento de erros

| Situação | Comportamento |
|----------|---------------|
| `queue/` não existe | Criado na inicialização |
| Nome de arquivo inválido na fila | Log warning, arquivo removido |
| `run_report` lança exceção | Log error com traceback, arquivo removido, loop continua |
| Relatório recente (< `REPORT_MIN_AGE_HOURS`) | Log info "skipped", arquivo removido |
| Permissão negada ao remover arquivo | Log warning, ignora na próxima iteração |

---

## Uso

**Host:**
```bash
# Iniciar watcher em background
python watch_queue.py &

# R ou qualquer processo dispara um ticker
touch queue/PETR4        # Linux/Mac
echo "" > queue/VALE3    # alternativa
```

**R:**
```r
file.create(file.path(queue_dir, ticker))  # idempotente
```

**Container (zero mudança de código):**
```yaml
services:
  report-watcher:
    build: .
    command: python watch_queue.py
    volumes:
      - ./queue:/app/queue
      - ./reports:/app/reports
```

---

## Testes

Arquivo: `tests/test_watch_queue.py`

Fixtures: `tmp_path` do pytest para diretórios isolados.

| Teste | O que verifica |
|-------|----------------|
| `test_gera_relatorio_se_ausente` | Sem relatório existente → `run_report` chamado, arquivo de fila removido |
| `test_skip_relatorio_recente` | Relatório com mtime < `report_min_age_hours` → `run_report` não chamado, arquivo de fila removido |
| `test_gera_relatorio_antigo` | Relatório com mtime > `report_min_age_hours` → `run_report` chamado |
| `test_erro_run_report_nao_trava_loop` | `run_report` lança exceção → arquivo de fila removido, sem propagação |
| `test_ticker_invalido_removido` | Nome de arquivo com caracteres inválidos → removido sem chamar `run_report` |
| `test_multiplos_tickers` | Dois tickers na fila → ambos processados independentemente |

`run_report` é mockado em todos os testes — sem chamadas de rede.

---

## Critérios de aceitação

1. `python watch_queue.py` inicia sem erro e cria `queue/` se ausente
2. `touch queue/PETR4` → relatório gerado em `reports/PETR4.md` em até `QUEUE_POLL_SECONDS` segundos
3. Segundo `touch queue/PETR4` em menos de `REPORT_MIN_AGE_HOURS` → relatório não regenerado
4. Exceção em `run_report` → watcher continua processando outros tickers
5. `pytest tests/test_watch_queue.py -v` — todos passam sem rede
