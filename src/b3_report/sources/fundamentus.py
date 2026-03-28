"""Source Fundamentus: indicadores de mercado via pynvest."""
import logging
import math

import pandas as pd
from pynvest.scrappers.fundamentus import Fundamentus

_logger = logging.getLogger(__name__)

_SECAO_MERCADO = [
    ("Empresa", "nome_empresa"),
    ("Setor", "nome_setor"),
    ("Subsetor", "nome_subsetor"),
    ("Cotação", "vlr_cot"),
    ("Data Últ. Cotação", "dt_ult_cot"),
    ("Mín. 52 sem.", "vlr_min_52_sem"),
    ("Máx. 52 sem.", "vlr_max_52_sem"),
    ("Vol. Méd. 2m", "vol_med_neg_2m"),
    ("Valor de Mercado", "vlr_mercado"),
    ("Valor da Firma (EV)", "vlr_firma"),
    ("Nº de Ações", "num_acoes"),
    ("Últ. Balanço", "dt_ult_balanco_proc"),
]

_SECAO_MULTIPLOS = [
    ("P/L", "vlr_ind_p_sobre_l"),
    ("P/VP", "vlr_ind_p_sobre_vp"),
    ("P/EBIT", "vlr_ind_p_sobre_ebit"),
    ("PSR", "vlr_ind_psr"),
    ("P/Ativo", "vlr_ind_p_sobre_ativ"),
    ("P/Cap.Giro", "vlr_ind_p_sobre_cap_giro"),
    ("P/Ativ.Circ.Liq", "vlr_ind_p_sobre_ativ_circ_liq"),
    ("EV/EBITDA", "vlr_ind_ev_sobre_ebitda"),
    ("EV/EBIT", "vlr_ind_ev_sobre_ebit"),
    ("Div. Yield", "vlr_ind_div_yield"),
    ("LPA", "vlr_ind_lpa"),
    ("VPA", "vlr_ind_vpa"),
]

_SECAO_RENTABILIDADE = [
    ("ROE", "vlr_ind_roe"),
    ("ROIC", "vlr_ind_roic"),
    ("Margem Bruta", "vlr_ind_margem_bruta"),
    ("Margem EBIT", "vlr_ind_margem_ebit"),
    ("Margem Líquida", "vlr_ind_margem_liq"),
    ("EBIT/Ativo", "vlr_ind_ebit_sobre_ativo"),
    ("Giro do Ativo", "vlr_ind_giro_ativos"),
    ("Cresc. Rec. 5a", "pct_cresc_rec_liq_ult_5a"),
]

_SECAO_BALANCO_DRE = [
    ("Ativo Total", "vlr_ativo"),
    ("Disponibilidades", "vlr_disponibilidades"),
    ("Ativo Circulante", "vlr_ativ_circulante"),
    ("Dívida Bruta", "vlr_divida_bruta"),
    ("Dívida Líquida", "vlr_divida_liq"),
    ("Patrimônio Líquido", "vlr_patrim_liq"),
    ("Liquidez Corrente", "vlr_liquidez_corr"),
    ("Dív.Bruta/Patrim.", "vlr_ind_divida_bruta_sobre_patrim"),
    ("Receita Líq. 12m", "vlr_receita_liq_ult_12m"),
    ("EBIT 12m", "vlr_ebit_ult_12m"),
    ("Lucro Líq. 12m", "vlr_lucro_liq_ult_12m"),
    ("Receita Líq. 3m", "vlr_receita_liq_ult_3m"),
    ("EBIT 3m", "vlr_ebit_ult_3m"),
    ("Lucro Líq. 3m", "vlr_lucro_liq_ult_3m"),
]

_SECAO_OSCILACOES = [
    ("Dia", "pct_var_dia"),
    ("Mês", "pct_var_mes"),
    ("30 dias", "pct_var_30d"),
    ("12 meses", "pct_var_12m"),
    ("Ano (a0)", "pct_var_ano_a0"),
    ("Ano -1", "pct_var_ano_a1"),
    ("Ano -2", "pct_var_ano_a2"),
]


def _val(row: pd.Series, col: str):
    if col not in row.index:
        return None
    v = row[col]
    if isinstance(v, float) and math.isnan(v):
        return None
    return str(v)


def _format_section(title: str, fields: list, row: pd.Series) -> str:
    lines = [title]
    for label, col in fields:
        v = _val(row, col)
        if v is not None:
            lines.append(f"- {label}: {v}")
    return "\n".join(lines) if len(lines) > 1 else ""


def _format(ticker: str, df: pd.DataFrame) -> str:
    row = df.iloc[0]
    sections = [
        _format_section("Dados de Mercado", _SECAO_MERCADO, row),
        _format_section("Múltiplos de Valuation", _SECAO_MULTIPLOS, row),
        _format_section("Rentabilidade", _SECAO_RENTABILIDADE, row),
        _format_section("Balanço e DRE (Fundamentus)", _SECAO_BALANCO_DRE, row),
        _format_section("Oscilações", _SECAO_OSCILACOES, row),
    ]
    body = "\n\n".join(s for s in sections if s)
    return f"Informações Complementares — {ticker}\n\n{body}"


def get_complementary_data(ticker: str) -> str:
    """Return formatted Fundamentus data for ticker via pynvest, or '' on failure."""
    try:
        df = Fundamentus().coleta_indicadores_de_ativo(ticker)
        if df is None or df.empty:
            return ""
        return _format(ticker, df)
    except Exception as e:
        _logger.warning("Fundamentus pynvest error for ticker=%s: %s", ticker, e)
        return ""
