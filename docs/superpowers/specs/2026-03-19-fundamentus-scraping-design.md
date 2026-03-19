# Design — Scraping Fundamentus (ETL)

**Data:** 2026-03-19
**Escopo:** Ingestão determinística de indicadores do Fundamentus no pipeline ETL existente

---

## Contexto

O ETL atual ingere dados da BRAPI (cotações, demonstrações financeiras) e grava em DuckDB. O Fundamentus complementa com ratios calculados (P/L, P/VP, EV/EBITDA, ROE etc.) e resumos financeiros em português, que a BRAPI não cobre ou cobre de forma incompleta.

O módulo existente `b3_report/sources/fundamentus.py` usa `crawl4ai + LLM` para geração de relatórios — essa abordagem é não-determinística e inadequada para ETL. Este design substitui o parser por extração direta do HTML, sem LLM.

A integração com o Fundamentus é tratada como **fallback complementar**: pode ser descontinuada no futuro se outra fonte cobrir os mesmos campos de forma mais confiável.

---

## Arquitetura

### Novo arquivo: `src/b3_etl/fundamentus.py`

Três funções públicas:

```python
def fetch_page(ticker: str, timeout: int = 15) -> str
    # urllib.request, retorna HTML bruto
    # URL: https://fundamentus.com.br/detalhes.php?papel={ticker}
    # Headers: User-Agent "b3-llm-report/etl"
    # 1 tentativa apenas (sem retry — Fundamentus é fonte secundária)

def parse_indicators(html: str) -> dict[str, str]
    # html.parser stdlib
    # Percorre pares <td>label</td><td>valor</td> nas tabelas da página
    # Retorna {label_normalizado: valor_raw} para todos os campos encontrados
    # Retorna {} se nenhuma tabela/campo reconhecido for encontrado

def _ingest_fundamentus_ticker(
    con, ticker: str, config: Config, fetched_at: datetime
) -> None
    # Chamada por ingest.py após o bloco BRAPI de cada ticker
    # Encapsula fetch_page + parse_indicators + gravação no DB
    # Qualquer exceção é capturada: log_error + return (sem propagação)
```

### Modificação: `src/b3_etl/ingest.py`

Após o `COMMIT` do bloco BRAPI e antes do `log_info("etl_ticker", ...)`:

```python
if con and not missing:
    _ingest_fundamentus_ticker(con, ticker, config, fetched_at)
```

Se `con` for `None` (skip_db) ou tabelas estiverem ausentes, o Fundamentus é pulado **inteiramente** — sem fetch HTTP, sem gravação de raw file. Isso é intencional: o Fundamentus é uma etapa de enriquecimento do banco, não um arquivo de dados brutos como o BRAPI. Em modo `skip_db` não há banco para enriquecer.

---

## Mapeamento de campos

Mapeamento fixo de ~20 campos prioritários. Campos não mapeados são ignorados.

| Label Fundamentus | Chave canônica | Destino |
|-------------------|---------------|---------|
| P/L | `pl` | ratios |
| P/VP | `pvp` | ratios |
| P/EBIT | `p_ebit` | ratios |
| EV/EBIT | `ev_ebit` | ratios |
| EV/EBITDA | `ev_ebitda` | ratios |
| Div.Yield | `dy` | ratios |
| ROE | `roe` | ratios |
| ROIC | `roic` | ratios |
| Marg. Bruta | `margem_bruta` | ratios |
| Marg. EBIT | `margem_ebit` | ratios |
| Marg. Líquida | `margem_liq` | ratios |
| Dív.Bruta/PL | `div_bruta_pl` | ratios |
| Liq. Corrente | `liq_corrente` | ratios |
| Receita Líq. | `receita_liq` | fundamentals/snapshot |
| EBIT | `ebit` | fundamentals/snapshot |
| Lucro Líquido | `lucro_liq` | fundamentals/snapshot |
| Ativo Total | `ativo_total` | fundamentals/balance |
| Patrim. Líq | `patrimonio_liq` | fundamentals/balance |
| Dívida Bruta | `divida_bruta` | fundamentals/balance |
| Caixa | `caixa` | fundamentals/balance |

**Dados adiados para o futuro:** oscilações (%), cotação, valor de mercado, número de ações.

---

## Gravação no DuckDB

### Tabela `ratios`

Um registro por campo mapeado como `ratios`:

```
ticker, period=fetched_at.date(), ratio_name=chave_canônica,
value=float, computed_at=fetched_at
```

Usa `_delete_then_insert` existente em `ingest.py` (por `ticker, period, ratio_name`).

### Tabela `fundamentals`

Um registro por campo mapeado como `fundamentals/*`:

```
ticker, period=fetched_at.date(), statement_type=("snapshot"|"balance"),
key=chave_canônica, value=float, currency="BRL",
source="fundamentus.com.br", fetched_at=fetched_at
```

Usa `_delete_then_insert` existente (por `ticker, period, statement_type, key`).

### Tabela `companies`

Adiado para iteração futura. A estrutura HTML do Fundamentus para setor/subsetor requer mapeamento específico, e a BRAPI já preenche esses campos em inglês. Evitar sobrescrever dados BRAPI com lógica parcialmente especificada.

### Raw files

`_save_raw` existente serializa `dict` como JSON e não aceita HTML. O Fundamentus usa gravação direta:

```python
ts = fetched_at.strftime("%Y%m%dT%H%M%SZ")
path_dir = os.path.join(config.raw_dir, "fundamentus", ticker)
os.makedirs(path_dir, exist_ok=True)
path = os.path.join(path_dir, f"{ts}.html")
content = html  # string UTF-8
with open(path, "w", encoding="utf-8") as f:
    f.write(content)
checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
size_bytes = os.path.getsize(path)
```

Após a gravação, `_delete_then_insert` registra em `raw_files` normalmente com `source="fundamentus.com.br"`.

---

## Tratamento de erros

Três camadas, todas não-fatais:

1. **Rede** — `urlopen` levanta exceção → `log_error("etl_ticker_fundamentus", ticker=..., error=...)` + return
2. **Parse vazio** — `parse_indicators` retorna `{}` → `log_error("etl_ticker_fundamentus", ticker=..., error="nenhum campo extraído")` + return
3. **Campo individual** — valor não conversível para float (via `_safe_float`) → campo ignorado silenciosamente; os demais são gravados normalmente

Nenhuma exceção propaga para `run_ingest`. O `rc` final de `run_ingest` não é afetado por falhas do Fundamentus.

### Transação

`_ingest_fundamentus_ticker` envolve todas as escritas no DuckDB em sua própria transação:

```python
con.execute("BEGIN")
# _delete_then_insert para ratios, fundamentals, raw_files
con.execute("COMMIT")
```

Em caso de exceção após `BEGIN`: `con.execute("ROLLBACK")` antes de `log_error` + return. Garante que falha parcial não deixa o DB em estado inconsistente.

---

## Conversão de valores

Reutiliza `_safe_float` de `ingest.py` que já trata formato BR (`1.234,56` → `1234.56`) e strings com `%`.

Valores percentuais do Fundamentus chegam como `"12,34%"` — `_safe_float` remove o `%` e converte para `12.34`. Os ratios são armazenados em **pontos percentuais** (ex.: ROE de 12,34% → `12.34`), não como fração decimal (`0.1234`). Consumidores do campo `ratios.value` devem dividir por 100 para obter a fração decimal quando necessário.

---

## Arquivos afetados

| Arquivo | Ação |
|---------|------|
| `src/b3_etl/fundamentus.py` | Criar |
| `src/b3_etl/ingest.py` | Editar — adicionar chamada `_ingest_fundamentus_ticker` |
| `tests/fixtures/fundamentus/PETR4.html` | Criar — fixture HTML estática |
| `tests/test_fundamentus.py` | Criar |

---

## O que não muda

- Interface pública de `run_ingest` (sem novos parâmetros).
- Schema DuckDB — tabelas `ratios` e `fundamentals` já existem.
- `requirements-etl.txt` — sem novas dependências (`html.parser` é stdlib).
- `b3_report/sources/fundamentus.py` — não alterado (continua sendo usado pelo pipeline de relatório).

---

## Testes

Fixtures HTML estáticas em `tests/fixtures/fundamentus/PETR4.html` (página real salva uma vez).

`parse_indicators` retorna `dict[str, str]` (valores raw como string). Conversão para float via `_safe_float` ocorre em `_ingest_fundamentus_ticker`, não em `parse_indicators`.

| Teste | O que verifica |
|-------|---------------|
| `test_parse_indicators_extrai_campos_principais` | `pl`, `pvp`, `roe`, `dy` presentes no resultado (valores como string) |
| `test_parse_indicators_html_sem_tabela` | retorna `{}` sem exceção |
| `test_fetch_page_retorna_html` | mock `urlopen`, verifica User-Agent correto |
| `test_ingest_fundamentus_popula_ratios` | DuckDB tmp, verifica `ratios` populada após chamada (valores float) |
| `test_ingest_fundamentus_falha_silenciosa` | `urlopen` para Fundamentus levanta exceção → `run_ingest` retorna `rc=0`, dados BRAPI intactos. Mock usa `side_effect` com inspeção de URL: URLs contendo `brapi.dev` retornam fixture BRAPI; URLs contendo `fundamentus` levantam `OSError`. |

---

## Critérios de aceitação

1. `python -m py_compile src/b3_etl/fundamentus.py` passa.
2. `python ingest.py --tickers PETR4` grava registros em `ratios` e `fundamentals` com `source='fundamentus.com.br'`.
3. Falha de rede no Fundamentus não altera `rc` de `run_ingest` nem dados BRAPI já gravados.
4. `pytest tests/test_fundamentus.py -v` — todos os testes passam sem acesso à rede.
