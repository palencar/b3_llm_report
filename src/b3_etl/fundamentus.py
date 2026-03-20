import urllib.parse
import urllib.request
from html.parser import HTMLParser

# ---------------------------------------------------------------------------
# Mapeamento: label Fundamentus → (chave canônica, destino)
# destino: "ratios" | "snapshot" | "balance"
# ---------------------------------------------------------------------------
_FIELD_MAP: dict[str, tuple[str, str]] = {
    "P/L":             ("pl",             "ratios"),
    "P/VP":            ("pvp",            "ratios"),
    "P/EBIT":          ("p_ebit",         "ratios"),
    "EV / EBIT":       ("ev_ebit",        "ratios"),
    "EV / EBITDA":     ("ev_ebitda",      "ratios"),
    "Div. Yield":      ("dy",             "ratios"),
    "ROE":             ("roe",            "ratios"),
    "ROIC":            ("roic",           "ratios"),
    "Marg. Bruta":     ("margem_bruta",   "ratios"),
    "Marg. EBIT":      ("margem_ebit",    "ratios"),
    "Marg. Líquida":   ("margem_liq",     "ratios"),
    "Div Br/ Patrim":  ("div_bruta_pl",   "ratios"),
    "Liquidez Corr":   ("liq_corrente",   "ratios"),
    "Receita Líquida": ("receita_liq",    "snapshot"),
    "EBIT":            ("ebit",           "snapshot"),
    "Lucro Líquido":   ("lucro_liq",      "snapshot"),
    "Ativo":           ("ativo_total",    "balance"),
    "Patrim. Líq":     ("patrimonio_liq", "balance"),
    "Dív. Bruta":      ("divida_bruta",   "balance"),
    "Disponibilidades":("caixa",          "balance"),
}

_FUNDAMENTUS_BASE = "https://fundamentus.com.br/detalhes.php"


# ---------------------------------------------------------------------------
# HTML Parser
# ---------------------------------------------------------------------------

class _IndicatorParser(HTMLParser):
    """Extrai pares label/valor de tabelas Fundamentus.

    Estrutura real do site:
        <td class="label ..."><span class="help tips">?</span><span class="txt">P/L</span></td>
        <td class="data ..."><span class="txt">5,47</span></td>

    Captura apenas o texto de <span class="txt"> para ignorar o "?" dos tooltips.
    """

    def __init__(self) -> None:
        super().__init__()
        self._in_td = False
        self._in_txt_span = False
        self._current_class: str = ""
        self._current_text: str = ""
        self._last_label: str | None = None
        self.indicators: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "td":
            self._in_td = True
            self._in_txt_span = False
            self._current_class = dict(attrs).get("class", "")
            self._current_text = ""
        elif tag == "span" and self._in_td:
            if dict(attrs).get("class", "") == "txt":
                self._in_txt_span = True
                self._current_text = ""  # só o conteúdo deste span

    def handle_data(self, data: str) -> None:
        if self._in_txt_span:
            self._current_text += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "span":
            self._in_txt_span = False
            return
        if tag != "td":
            return
        self._in_td = False
        self._in_txt_span = False
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
