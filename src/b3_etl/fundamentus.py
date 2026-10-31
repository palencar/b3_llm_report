"""Mapeamento e delegação para o módulo compartilhado de Fundamentus."""

# ---------------------------------------------------------------------------
# Mapeamento: label do site → (chave canônica, destino)
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

# ---------------------------------------------------------------------------
# Delegação para o módulo compartilhado (b3_core.fundamentus)
# ---------------------------------------------------------------------------
from b3_core.fundamentus import (  # noqa: F401
    parse_indicators as parse_indicators,
    fetch_page as fetch_page,
)

# Re-export for ingest.py and tests — same public API.
# (parse_indicators, fetch_page are already imported above; keeping explicit for clarity)
__all__ = ["_FIELD_MAP", "parse_indicators", "fetch_page"]
