# Scraping Fundamentus — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar scraping determinístico do Fundamentus ao pipeline ETL, gravando ratios e resumos financeiros em DuckDB como complemento ao BRAPI, sem novas dependências de runtime.

**Architecture:** `src/b3_etl/fundamentus.py` contém apenas `fetch_page` (urllib) e `parse_indicators` (html.parser stdlib). A função de orquestração `_ingest_fundamentus_ticker` fica em `ingest.py` para reutilizar `_safe_float` e `_delete_then_insert` sem importação circular. `ingest.py` importa `fetch_page`, `parse_indicators` e `_FIELD_MAP` de `fundamentus.py` e chama `_ingest_fundamentus_ticker` após o COMMIT BRAPI de cada ticker.

**Tech Stack:** Python stdlib (`urllib.request`, `html.parser`, `hashlib`), DuckDB, pytest, `unittest.mock`.

---

## Estrutura de arquivos

| Arquivo | Ação |
|---------|------|
| `src/b3_etl/fundamentus.py` | Criar — `fetch_page`, `parse_indicators`, `_FIELD_MAP` |
| `src/b3_etl/ingest.py` | Editar — import + `_ingest_fundamentus_ticker` + chamada no loop |
| `tests/fixtures/fundamentus/PETR4.html` | Criar — fixture HTML estática para testes |
| `tests/test_fundamentus.py` | Criar — todos os testes do módulo |

---

### Task 1: Fixture HTML + `parse_indicators`

**Files:**
- Create: `tests/fixtures/fundamentus/PETR4.html`
- Create: `src/b3_etl/fundamentus.py` (apenas `_FIELD_MAP` + `parse_indicators`)
- Create: `tests/test_fundamentus.py` (2 primeiros testes)

- [ ] **Step 1: Criar diretório e fixture HTML**

```bash
mkdir -p tests/fixtures/fundamentus
```

Criar `tests/fixtures/fundamentus/PETR4.html`:

```html
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Fundamentus - PETR4</title></head>
<body>
<table>
  <tr>
    <td class="label"><span class="txt">P/L</span></td>
    <td class="data"><span class="txt">8,53</span></td>
    <td class="label"><span class="txt">P/VP</span></td>
    <td class="data"><span class="txt">1,24</span></td>
  </tr>
  <tr>
    <td class="label"><span class="txt">P/EBIT</span></td>
    <td class="data"><span class="txt">5,87</span></td>
    <td class="label"><span class="txt">EV/EBIT</span></td>
    <td class="data"><span class="txt">5,12</span></td>
  </tr>
  <tr>
    <td class="label"><span class="txt">EV/EBITDA</span></td>
    <td class="data"><span class="txt">4,31</span></td>
    <td class="label"><span class="txt">Div.Yield</span></td>
    <td class="data"><span class="txt">12,34%</span></td>
  </tr>
  <tr>
    <td class="label"><span class="txt">ROE</span></td>
    <td class="data"><span class="txt">14,56%</span></td>
    <td class="label"><span class="txt">ROIC</span></td>
    <td class="data"><span class="txt">11,23%</span></td>
  </tr>
  <tr>
    <td class="label"><span class="txt">Marg. Bruta</span></td>
    <td class="data"><span class="txt">53,12%</span></td>
    <td class="label"><span class="txt">Marg. EBIT</span></td>
    <td class="data"><span class="txt">37,01%</span></td>
  </tr>
  <tr>
    <td class="label"><span class="txt">Marg. Líquida</span></td>
    <td class="data"><span class="txt">23,64%</span></td>
    <td class="label"><span class="txt">Dív.Bruta/PL</span></td>
    <td class="data"><span class="txt">0,89</span></td>
  </tr>
  <tr>
    <td class="label"><span class="txt">Liq. Corrente</span></td>
    <td class="data"><span class="txt">1,45</span></td>
    <td class="label"></td>
    <td class="data"></td>
  </tr>
  <tr>
    <td class="label"><span class="txt">Receita Líq.</span></td>
    <td class="data"><span class="txt">527.000.000</span></td>
    <td class="label"><span class="txt">EBIT</span></td>
    <td class="data"><span class="txt">195.000.000</span></td>
  </tr>
  <tr>
    <td class="label"><span class="txt">Lucro Líquido</span></td>
    <td class="data"><span class="txt">124.600.000</span></td>
    <td class="label"><span class="txt">Ativo Total</span></td>
    <td class="data"><span class="txt">980.000.000</span></td>
  </tr>
  <tr>
    <td class="label"><span class="txt">Patrim. Líq</span></td>
    <td class="data"><span class="txt">360.000.000</span></td>
    <td class="label"><span class="txt">Dívida Bruta</span></td>
    <td class="data"><span class="txt">320.000.000</span></td>
  </tr>
  <tr>
    <td class="label"><span class="txt">Caixa</span></td>
    <td class="data"><span class="txt">68.000.000</span></td>
    <td class="label"></td>
    <td class="data"></td>
  </tr>
</table>
</body>
</html>
```

> **Nota:** Este fixture usa a estrutura HTML esperada do Fundamentus (labels em `<td class="label">`, valores em `<td class="data">`, texto dentro de `<span class="txt">`). Se os testes falharem com valores inesperados, substituir pela página real:
> ```bash
> curl -L -o tests/fixtures/fundamentus/PETR4.html "https://fundamentus.com.br/detalhes.php?papel=PETR4"
> ```
> e ajustar `_IndicatorParser` conforme a estrutura encontrada.

- [ ] **Step 2: Escrever testes falhando**

Criar `tests/test_fundamentus.py`:

```python
"""Testes para src/b3_etl/fundamentus.py e integração em ingest.py."""
import os

from b3_etl.fundamentus import parse_indicators

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "fundamentus")


def _load_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return f.read()


def test_parse_indicators_extrai_campos_principais():
    html = _load_fixture("PETR4.html")
    result = parse_indicators(html)
    assert "P/L" in result
    assert "P/VP" in result
    assert "ROE" in result
    assert "Div.Yield" in result
    # valores são strings raw (conversão para float ocorre em _ingest_fundamentus_ticker)
    assert result["P/L"] == "8,53"
    assert result["Div.Yield"] == "12,34%"


def test_parse_indicators_html_sem_tabela():
    result = parse_indicators("<html><body>Sem tabelas aqui.</body></html>")
    assert result == {}
```

- [ ] **Step 3: Executar testes — devem falhar**

```bash
python -m pytest tests/test_fundamentus.py::test_parse_indicators_extrai_campos_principais tests/test_fundamentus.py::test_parse_indicators_html_sem_tabela -v
```

Esperado: `ImportError: cannot import name 'parse_indicators' from 'b3_etl.fundamentus'`

- [ ] **Step 4: Criar `src/b3_etl/fundamentus.py` com `_FIELD_MAP` e `parse_indicators`**

```python
import hashlib
import os
import urllib.parse
import urllib.request
from html.parser import HTMLParser

# ---------------------------------------------------------------------------
# Mapeamento: label Fundamentus → (chave canônica, destino)
# destino: "ratios" | "snapshot" | "balance"
# ---------------------------------------------------------------------------
_FIELD_MAP: dict[str, tuple[str, str]] = {
    "P/L":           ("pl",            "ratios"),
    "P/VP":          ("pvp",           "ratios"),
    "P/EBIT":        ("p_ebit",        "ratios"),
    "EV/EBIT":       ("ev_ebit",       "ratios"),
    "EV/EBITDA":     ("ev_ebitda",     "ratios"),
    "Div.Yield":     ("dy",            "ratios"),
    "ROE":           ("roe",           "ratios"),
    "ROIC":          ("roic",          "ratios"),
    "Marg. Bruta":   ("margem_bruta",  "ratios"),
    "Marg. EBIT":    ("margem_ebit",   "ratios"),
    "Marg. Líquida": ("margem_liq",    "ratios"),
    "Dív.Bruta/PL":  ("div_bruta_pl",  "ratios"),
    "Liq. Corrente": ("liq_corrente",  "ratios"),
    "Receita Líq.":  ("receita_liq",   "snapshot"),
    "EBIT":          ("ebit",          "snapshot"),
    "Lucro Líquido": ("lucro_liq",     "snapshot"),
    "Ativo Total":   ("ativo_total",   "balance"),
    "Patrim. Líq":   ("patrimonio_liq","balance"),
    "Dívida Bruta":  ("divida_bruta",  "balance"),
    "Caixa":         ("caixa",         "balance"),
}

_FUNDAMENTUS_BASE = "https://fundamentus.com.br/detalhes.php"


# ---------------------------------------------------------------------------
# HTML Parser
# ---------------------------------------------------------------------------

class _IndicatorParser(HTMLParser):
    """Extrai pares label/valor de tabelas Fundamentus.

    Estrutura esperada:
        <td class="label"><span class="txt">P/L</span></td>
        <td class="data"><span class="txt">8,53</span></td>
    """

    def __init__(self) -> None:
        super().__init__()
        self._in_td = False
        self._current_class: str = ""
        self._current_text: str = ""
        self._last_label: str | None = None
        self.indicators: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "td":
            self._in_td = True
            self._current_class = dict(attrs).get("class", "")
            self._current_text = ""

    def handle_data(self, data: str) -> None:
        if self._in_td:
            self._current_text += data

    def handle_endtag(self, tag: str) -> None:
        if tag != "td":
            return
        self._in_td = False
        text = " ".join(self._current_text.split())  # normaliza espaços/newlines
        if "label" in self._current_class:
            self._last_label = text if text else None
        elif "data" in self._current_class and self._last_label:
            self.indicators[self._last_label] = text
            self._last_label = None


def parse_indicators(html: str) -> dict[str, str]:
    """Extrai pares label→valor das tabelas da página Fundamentus.

    Retorna dict com labels como chave e valores raw (strings) como valor.
    Retorna {} se nenhum campo for encontrado.
    """
    parser = _IndicatorParser()
    parser.feed(html)
    return parser.indicators


# ---------------------------------------------------------------------------
# HTTP fetch
# ---------------------------------------------------------------------------

def fetch_page(ticker: str, timeout: int = 15) -> str:
    """Baixa a página de detalhes do Fundamentus para o ticker.

    Retorna HTML como string (decodificado em latin-1, encoding do site).
    Levanta OSError/urllib.error.URLError em falha de rede — sem retry
    (Fundamentus é fonte secundária; falha não é crítica).
    """
    url = f"{_FUNDAMENTUS_BASE}?papel={urllib.parse.quote(ticker)}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "b3-llm-report/etl",
            "Accept": "text/html",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read().decode("latin-1")
```

- [ ] **Step 5: Executar testes — devem passar**

```bash
python -m pytest tests/test_fundamentus.py::test_parse_indicators_extrai_campos_principais tests/test_fundamentus.py::test_parse_indicators_html_sem_tabela -v
```

Esperado: `2 passed`

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/fundamentus/PETR4.html tests/test_fundamentus.py src/b3_etl/fundamentus.py
git commit -m "feat: parse_indicators determinístico para Fundamentus"
```

---

### Task 2: Teste de `fetch_page`

**Files:**
- Modify: `tests/test_fundamentus.py` — adicionar teste + helper `_make_response`

- [ ] **Step 1: Escrever teste falhando**

Adicionar em `tests/test_fundamentus.py` (após os imports existentes):

```python
from unittest.mock import patch, MagicMock

from b3_etl.fundamentus import fetch_page


def _make_response(content: str, encoding: str = "latin-1") -> MagicMock:
    """Helper: mock compatível com 'with urlopen(...) as resp'."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = content.encode(encoding)
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def test_fetch_page_retorna_html():
    html_content = "<html><body>ok</body></html>"
    with patch("urllib.request.urlopen", return_value=_make_response(html_content)) as mock_open:
        result = fetch_page("PETR4")
    assert "ok" in result
    req = mock_open.call_args[0][0]
    assert "PETR4" in req.full_url
    assert req.get_header("User-agent") == "b3-llm-report/etl"
```

- [ ] **Step 2: Executar teste — deve passar**

`fetch_page` já foi implementada na Task 1. Execute:

```bash
python -m pytest tests/test_fundamentus.py::test_fetch_page_retorna_html -v
```

Esperado: `1 passed`

- [ ] **Step 4: Commit**

```bash
git add tests/test_fundamentus.py
git commit -m "test: cobre fetch_page com mock urlopen"
```

---

### Task 3: `_ingest_fundamentus_ticker` em `ingest.py`

`_ingest_fundamentus_ticker` fica em `ingest.py` (não em `fundamentus.py`) para reutilizar `_safe_float` e `_delete_then_insert` sem criar importação circular. `ingest.py` importa `fetch_page`, `parse_indicators` e `_FIELD_MAP` de `fundamentus.py`.

**Files:**
- Modify: `src/b3_etl/ingest.py` — import + nova função `_ingest_fundamentus_ticker`
- Modify: `tests/test_fundamentus.py` — 2 novos testes

- [ ] **Step 1: Escrever testes falhando**

Adicionar em `tests/test_fundamentus.py`:

```python
import json
from datetime import datetime, timezone

from b3_etl.ingest import _ingest_fundamentus_ticker, run_ingest
from b3_core.config import load_config
from b3_storage.schema import SCHEMA_SQL
from b3_storage.db import connect


def _init_db(db_path: str) -> None:
    con = connect(db_path, read_only=False)
    for stmt in SCHEMA_SQL.split(";"):
        stmt = stmt.strip()
        if stmt:
            con.execute(stmt)
    con.close()


def test_ingest_fundamentus_popula_ratios(tmp_path):
    """_ingest_fundamentus_ticker deve gravar ratios, fundamentals e raw_files."""
    db_path = str(tmp_path / "test.duckdb")
    _init_db(db_path)
    html = _load_fixture("PETR4.html")
    config = load_config()
    config = config.__class__(
        **{**config.__dict__, "raw_dir": str(tmp_path / "raw")}
    )
    fetched_at = datetime.now(timezone.utc).replace(tzinfo=None)
    con = connect(db_path, read_only=False)
    # latin-1: fetch_page decodifica a resposta como latin-1; o mock deve
    # codificar da mesma forma para que caracteres acentuados nos nomes de
    # campo (ex.: "Marg. Líquida") sobrevivam à codificação/decodificação.
    with patch("urllib.request.urlopen", return_value=_make_response(html, "latin-1")):
        _ingest_fundamentus_ticker(con, "PETR4", config, fetched_at)
    con.close()

    con = connect(db_path, read_only=True)
    ratio_count = con.execute(
        "SELECT COUNT(*) FROM ratios WHERE ticker = 'PETR4'"
    ).fetchone()[0]
    fund_count = con.execute(
        "SELECT COUNT(*) FROM fundamentals WHERE ticker = 'PETR4' AND source = 'fundamentus.com.br'"
    ).fetchone()[0]
    raw_count = con.execute(
        "SELECT COUNT(*) FROM raw_files WHERE source = 'fundamentus.com.br'"
    ).fetchone()[0]
    con.close()

    assert ratio_count >= 8   # pelo menos 8 ratios do fixture (pl, pvp, roe, roic, dy, margens...)
    assert fund_count >= 3    # receita_liq, ebit, lucro_liq + campos balance
    assert raw_count == 1     # HTML bruto registrado


def test_ingest_fundamentus_falha_silenciosa(tmp_path):
    """Falha de rede no Fundamentus não altera rc=0 nem dados BRAPI já gravados."""
    db_path = str(tmp_path / "test.duckdb")
    _init_db(db_path)
    brapi_fixture_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "brapi", "PETR4.json"
    )
    with open(brapi_fixture_path) as f:
        brapi_data = json.load(f)

    def fake_urlopen(req, timeout=30):
        if "brapi.dev" in req.full_url:
            payload = json.dumps(brapi_data).encode("utf-8")
            mock_resp = MagicMock()
            mock_resp.read.return_value = payload
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp
        raise OSError("simulando falha de rede no Fundamentus")

    config = load_config()
    config = config.__class__(
        **{
            **config.__dict__,
            "db_path": db_path,
            "raw_dir": str(tmp_path / "raw"),
            "snapshot_dir": str(tmp_path / "snapshots"),
        }
    )
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        rc = run_ingest(["PETR4"], config, ["financialData"], write_snapshot=False)

    assert rc == 0
    con = connect(db_path, read_only=True)
    companies = con.execute(
        "SELECT ticker FROM companies WHERE ticker = 'PETR4'"
    ).fetchall()
    con.close()
    assert len(companies) == 1  # dados BRAPI intactos
```

- [ ] **Step 2: Executar testes — devem falhar**

```bash
python -m pytest tests/test_fundamentus.py::test_ingest_fundamentus_popula_ratios tests/test_fundamentus.py::test_ingest_fundamentus_falha_silenciosa -v
```

Esperado: `ImportError: cannot import name '_ingest_fundamentus_ticker' from 'b3_etl.ingest'`

- [ ] **Step 3: Adicionar import em `ingest.py`**

No topo de `src/b3_etl/ingest.py`, após a linha `from b3_etl.brapi import fetch_quote, BrapiError`, adicionar:

```python
from b3_etl.fundamentus import fetch_page, parse_indicators, _FIELD_MAP
```

- [ ] **Step 4: Implementar `_ingest_fundamentus_ticker` em `ingest.py`**

Adicionar a função após `_write_snapshot` e antes de `run_ingest`:

```python
def _ingest_fundamentus_ticker(
    con,
    ticker: str,
    config: Config,
    fetched_at: datetime,
) -> None:
    """Busca e grava indicadores do Fundamentus para um ticker.

    Não propaga exceções — falhas são logadas e a execução continua.
    Escritas no DuckDB são atômicas (BEGIN/COMMIT/ROLLBACK próprios).
    Ratios são gravados em pontos percentuais (ex.: ROE 14,56% → 14.56).
    """
    try:
        html = fetch_page(ticker)
    except Exception as exc:
        log_error("etl_ticker_fundamentus", ticker=ticker, error=str(exc))
        return

    raw_indicators = parse_indicators(html)
    if not raw_indicators:
        log_error(
            "etl_ticker_fundamentus", ticker=ticker, error="nenhum campo extraído"
        )
        return

    # gravar HTML bruto
    ts = fetched_at.strftime("%Y%m%dT%H%M%SZ")
    path_dir = os.path.join(config.raw_dir, "fundamentus", ticker)
    os.makedirs(path_dir, exist_ok=True)
    path = os.path.join(path_dir, f"{ts}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    checksum = hashlib.sha256(html.encode("utf-8")).hexdigest()
    size_bytes = os.path.getsize(path)

    source = "fundamentus.com.br"
    try:
        con.execute("BEGIN")
        for label, raw_value in raw_indicators.items():
            if label not in _FIELD_MAP:
                continue
            canonical_key, dest = _FIELD_MAP[label]
            value = _safe_float(raw_value)
            if value is None:
                continue
            if dest == "ratios":
                _delete_then_insert(
                    con,
                    "ratios",
                    ["ticker", "period", "ratio_name"],
                    [ticker, fetched_at.date(), canonical_key],
                    [ticker, fetched_at.date(), canonical_key, value, fetched_at],
                    ["ticker", "period", "ratio_name", "value", "computed_at"],
                )
            else:  # "snapshot" ou "balance"
                _delete_then_insert(
                    con,
                    "fundamentals",
                    ["ticker", "period", "statement_type", "key"],
                    [ticker, fetched_at.date(), dest, canonical_key],
                    [
                        ticker, fetched_at.date(), dest, canonical_key,
                        value, "BRL", source, fetched_at,
                    ],
                    ["ticker", "period", "statement_type", "key",
                     "value", "currency", "source", "fetched_at"],
                )
        _delete_then_insert(
            con,
            "raw_files",
            ["source", "path"],
            [source, path],
            [source, path, fetched_at, checksum, size_bytes],
            ["source", "path", "fetched_at", "checksum", "size_bytes"],
        )
        con.execute("COMMIT")
    except Exception as exc:
        con.execute("ROLLBACK")
        log_error("etl_ticker_fundamentus", ticker=ticker, error=str(exc))
```

- [ ] **Step 5: Executar testes — devem passar**

```bash
python -m pytest tests/test_fundamentus.py::test_ingest_fundamentus_popula_ratios tests/test_fundamentus.py::test_ingest_fundamentus_falha_silenciosa -v
```

Esperado: `2 passed`

- [ ] **Step 6: Commit**

```bash
git add src/b3_etl/ingest.py tests/test_fundamentus.py
git commit -m "feat: _ingest_fundamentus_ticker grava ratios e fundamentals no DuckDB"
```

---

### Task 4: Integração em `run_ingest`

**Files:**
- Modify: `src/b3_etl/ingest.py` — adicionar chamada após bloco BRAPI

- [ ] **Step 1: Localizar ponto de inserção**

Em `src/b3_etl/ingest.py`, localizar o trecho (atualmente linhas 327–339):

```python
                con.execute("COMMIT")
            except Exception as exc:
                con.execute("ROLLBACK")
                log_error("etl_ticker", ticker=ticker, error=str(exc))
                continue

        log_info(
            "etl_ticker",
            ticker=ticker,
            ...
        )
```

- [ ] **Step 2: Inserir chamada entre `continue` e `log_info`**

O trecho deve ficar:

```python
                con.execute("COMMIT")
            except Exception as exc:
                con.execute("ROLLBACK")
                log_error("etl_ticker", ticker=ticker, error=str(exc))
                continue

        if con and not missing:
            _ingest_fundamentus_ticker(con, ticker, config, fetched_at)

        log_info(
            "etl_ticker",
            ticker=ticker,
            rows_fundamentals=len(fundamentals_records),
            rows_prices=rows_prices,
            duration_ms=int((time.time() - ticker_start) * 1000),
        )
```

- [ ] **Step 3: Atualizar `test_run_ingest_three_tickers` em `tests/test_brapi_integration.py`**

Após a integração, `run_ingest` também chama `urlopen` para o Fundamentus. O `fake_urlopen` existente usa `req.full_url.split("/quote/")[1]` que levantaria `IndexError` para URLs do Fundamentus. Atualizar:

```python
def fake_urlopen(req, timeout=30):
    if "brapi.dev" in req.full_url:
        ticker = req.full_url.split("/quote/")[1].split("?")[0]
        call_count["n"] += 1
        return _make_urlopen_mock(fixtures[ticker])
    # Fundamentus — simular falha silenciosa (sem DB write, sem quebrar o job)
    raise OSError("fundamentus bloqueado no teste")
```

- [ ] **Step 4: Executar suíte completa**

```bash
python -m pytest tests/ -v
```

Esperado: todos os testes passando (22 existentes + 5 novos = 27 passed)

- [ ] **Step 5: Verificar sintaxe**

```bash
python -m py_compile src/b3_etl/fundamentus.py src/b3_etl/ingest.py
```

Esperado: sem saída (silencioso = sucesso)

- [ ] **Step 6: Commit**

```bash
git add src/b3_etl/ingest.py tests/test_brapi_integration.py
git commit -m "feat: integra Fundamentus no loop de run_ingest após COMMIT BRAPI"
```

---

## Comandos para teste manual (após implementação)

```bash
# 1. Inicializar DB (se ainda não existir)
python init_db.py

# 2. Ingerir um ticker — verifica logs JSON no stdout
python ingest.py --tickers PETR4 --skip-snapshot

# 3. Confirmar ratios gravados
python -c "
import duckdb
con = duckdb.connect('data/duckdb/b3_fundamentals.duckdb', read_only=True)
rows = con.execute(\"SELECT ratio_name, value FROM ratios WHERE ticker='PETR4' ORDER BY ratio_name\").fetchall()
for r in rows: print(r)
con.close()
"

# 4. Confirmar fundamentals do Fundamentus
python -c "
import duckdb
con = duckdb.connect('data/duckdb/b3_fundamentals.duckdb', read_only=True)
rows = con.execute(\"SELECT key, value FROM fundamentals WHERE ticker='PETR4' AND source='fundamentus.com.br'\").fetchall()
for r in rows: print(r)
con.close()
"

# 5. Confirmar raw file HTML gravado
ls data/raw/fundamentus/PETR4/
```
