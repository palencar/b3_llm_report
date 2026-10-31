"""Shared Fundamentus module: parser, fetch, label→key mapping, DataFrame builder.

Replaces pynvest as the canonical source for Fundamentus web scraping and data
mapping. Both ETL and report layers import from here.
"""
from datetime import datetime

import pandas as pd
import urllib.parse
import urllib.request
from html.parser import HTMLParser

# ---------------------------------------------------------------------------
# Mapeamento: label do site → coluna canônica
# ---------------------------------------------------------------------------
LABEL_TO_KEY: dict[str, str] = {
    "Papel": "nome_papel",
    "Tipo": "tipo_papel",
    "Empresa": "nome_empresa",
    "Setor": "nome_setor",
    "Subsetor": "nome_subsetor",
    "Cotação": "vlr_cot",
    "Data últ cot": "dt_ult_cot",
    "Min 52 sem": "vlr_min_52_sem",
    "Max 52 sem": "vlr_max_52_sem",
    "Vol $ méd (2m)": "vol_med_neg_2m",
    "Valor de mercado": "vlr_mercado",
    "Valor da firma": "vlr_firma",
    "Últ balanço processado": "dt_ult_balanco_proc",
    "Nro. Ações": "num_acoes",
    "Dia": "pct_var_dia",
    "Mês": "pct_var_mes",
    "30 dias": "pct_var_30d",
    "12 meses": "pct_var_12m",
    str(datetime.now().year): "pct_var_ano_a0",
    str(datetime.now().year - 1): "pct_var_ano_a1",
    str(datetime.now().year - 2): "pct_var_ano_a2",
    str(datetime.now().year - 3): "pct_var_ano_a3",
    str(datetime.now().year - 4): "pct_var_ano_a4",
    str(datetime.now().year - 5): "pct_var_ano_a5",
    "P/L": "vlr_ind_p_sobre_l",
    "P/VP": "vlr_ind_p_sobre_vp",
    "P/EBIT": "vlr_ind_p_sobre_ebit",
    "PSR": "vlr_ind_psr",
    "P/Ativos": "vlr_ind_p_sobre_ativ",
    "P/Cap. Giro": "vlr_ind_p_sobre_cap_giro",
    "P/Ativ Circ Liq": "vlr_ind_p_sobre_ativ_circ_liq",
    "Div. Yield": "vlr_ind_div_yield",
    "EV / EBITDA": "vlr_ind_ev_sobre_ebitda",
    "EV / EBIT": "vlr_ind_ev_sobre_ebit",
    "Cres. Rec (5a)": "pct_cresc_rec_liq_ult_5a",
    "LPA": "vlr_ind_lpa",
    "VPA": "vlr_ind_vpa",
    "Marg. Bruta": "vlr_ind_margem_bruta",
    "Marg. EBIT": "vlr_ind_margem_ebit",
    "Marg. Líquida": "vlr_ind_margem_liq",
    "EBIT / Ativo": "vlr_ind_ebit_sobre_ativo",
    "ROIC": "vlr_ind_roic",
    "ROE": "vlr_ind_roe",
    "Liquidez Corr": "vlr_liquidez_corr",
    "Div Br/ Patrim": "vlr_ind_divida_bruta_sobre_patrim",
    "Giro Ativos": "vlr_ind_giro_ativos",
    "Ativo": "vlr_ativo",
    "Disponibilidades": "vlr_disponibilidades",
    "Ativo Circulante": "vlr_ativ_circulante",
    "Dív. Bruta": "vlr_divida_bruta",
    "Dív. Líquida": "vlr_divida_liq",
    "Patrim. Líq": "vlr_patrim_liq",
    "Receita Líquida_1": "vlr_receita_liq_ult_12m",
    "EBIT_1": "vlr_ebit_ult_12m",
    "Lucro Líquido_1": "vlr_lucro_liq_ult_12m",
    "Receita Líquida": "vlr_receita_liq_ult_3m",
    "EBIT": "vlr_ebit_ult_3m",
    "Lucro Líquido": "vlr_lucro_liq_ult_3m",
}

# ---------------------------------------------------------------------------
# HTML Parser — verbatim from b3_etl/fundamentus.py (lines 39-86)
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

    O parser procura o bloco HTML cuja classe indica "label" + "data" e extrai
    todos os pares label/valor encontrados nas células ``<td class="label">`` e
    ``<td class="data">`` adjacentes.
    """
    parser = _IndicatorParser()
    parser.feed(html)
    return parser.indicators


# ---------------------------------------------------------------------------
# HTTP fetch — verbatim from b3_etl/fundamentus.py (lines 104-121)
# ---------------------------------------------------------------------------

_FUNDAMENTUS_BASE = "https://fundamentus.com.br/detalhes.php"


def fetch_page(ticker: str, timeout: int = 15) -> str:
    """Baixa a página de detalhes do Fundamentus para o ticker.

    Retorna o HTML (latin-1) como ``str``. Se a requisição falhar por timeout ou
    erro de rede, levanta :exc:`URLError`.
    """
    query_str = f"{_FUNDAMENTUS_BASE}?{urllib.parse.urlencode({'papel': ticker})}"

    req = urllib.request.Request(
        query_str,
        headers={"User-agent": "b3-llm-report/etl"},
    )
    response = urllib.request.urlopen(req, timeout=timeout)
    return response.read().decode("latin-1")


def fetch_indicators(ticker: str, timeout: int = 15) -> dict[str, str]:
    """Fetch page and parse indicators in one call."""
    html = fetch_page(ticker, timeout)
    return parse_indicators(html)


def indicators_to_dataframe(indicators: dict[str, str]) -> pd.DataFrame:
    """Return a single-row DataFrame keyed by LABEL_TO_KEY values (raw strings)."""
    cols = list(LABEL_TO_KEY.values())
    row: dict[str, object] = {}
    for label, key in LABEL_TO_KEY.items():
        row[key] = indicators.get(label)  # None for missing labels
    return pd.DataFrame([row], columns=cols)
