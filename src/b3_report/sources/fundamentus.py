"""Source Fundamentus: indicadores de mercado via DB-first com cache DuckDB."""
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

from b3_core.fundamentus import LABEL_TO_KEY, indicators_to_dataframe
from b3_storage.fundamentus import load_cache, latest_fetch, save_cache

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
    ("P/Ativos", "vlr_ind_p_sobre_ativ"),
    ("P/Cap. Giro", "vlr_ind_p_sobre_cap_giro"),
    ("P/Ativ Circ Liq", "vlr_ind_p_sobre_ativ_circ_liq"),
    ("Div. Yield", "vlr_ind_div_yield"),
    ("EV / EBITDA", "vlr_ind_ev_sobre_ebitda"),
    ("EV / EBIT", "vlr_ind_ev_sobre_ebit"),
]

_SECAO_RENTABILIDADE = [
    ("ROE", "vlr_ind_roe"),
    ("ROIC", "vlr_ind_roic"),
    ("Marg. Bruta", "vlr_ind_margem_bruta"),
    ("Marg. EBIT", "vlr_ind_margem_ebit"),
    ("Marg. Líquida", "vlr_ind_margem_liq"),
]

_SECAO_BALANCO_DRE = [
    ("EBIT", "vlr_ebit_ult_3m"),
    ("Receita Líq 3m", "vlr_receita_liq_ult_3m"),
    ("Lucro Líq 3m", "vlr_lucro_liq_ult_3m"),
    ("EBIT 12m", "vlr_ebit_ult_12m"),
    ("Receita Líq 12m", "vlr_receita_liq_ult_12m"),
    ("Lucro Líq 12m", "vlr_lucro_liq_ult_12m"),
    ("Ativo Total", "vlr_ativo"),
    ("Patrimônio Líq", "vlr_patrim_liq"),
    ("Dívida Bruta", "vlr_divida_bruta"),
    ("Disponibilidades", "vlr_disponibilidades"),
]

_SECAO_OSCILACOES = [
    ("Var. Dia", "pct_var_dia"),
    ("Var. Mês", "pct_var_mes"),
    ("Var. 30 dias", "pct_var_30d"),
    ("Var. 12 meses", "pct_var_12m"),
]


def _val(row: pd.Series, col: str):
    if col not in row.index:
        return None
    v = row[col]
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass  # pd.isna raises on array-like values
    s = str(v)
    return None if not s else s


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


def get_complementary_payload(
    ticker: str,
    db_path: Optional[str] = None,
    ttl_seconds: int = 86400,
) -> dict:
    """Retorna texto, indicadores originais e timestamp da coleta/cache.

    Flow: read cache first (DB-first), fetch online if miss/expired, write
    cache on fetch. Sem uso de cache vencido em caso de erro. fetched_at
    preserva o horario local do cache, nao representa publicacao dos dados.
    """
    _logger.info("fundamentus_cache_check ticker=%s", ticker)

    # ------------------------------------------------------------------ cache hit
    if db_path and os.path.exists(db_path):
        fetched_at = latest_fetch(db_path, ticker)
        if fetched_at:
            if isinstance(fetched_at, str):
                fetched_at_dt = datetime.fromisoformat(fetched_at)
            else:
                fetched_at_dt = fetched_at

            cache_age = (datetime.now() - fetched_at_dt).total_seconds()
            if cache_age < ttl_seconds:
                cached = load_cache(db_path, ticker)
                if cached:
                    _logger.info("fundamentus_cache_hit ticker=%s", ticker)
                    return {"text": _format(ticker, indicators_to_dataframe(cached)),
                            "indicators": cached, "fetched_at": fetched_at_dt.isoformat()}

    # ----------------------------------------------------------------- online
    try:
        from b3_core.fundamentus import fetch_indicators as _fetch_indicators

        raw = _fetch_indicators(ticker)
        if not raw:
            _logger.warning("fundamentus_fetch_empty ticker=%s", ticker)
            return {"text": "", "indicators": {}, "fetched_at": None}
    except Exception as e:
        _logger.warning("fundamentus_fetch_error ticker=%s error=%s", ticker, str(e))
        return {"text": "", "indicators": {}, "fetched_at": None}

    df = indicators_to_dataframe(raw)
    fetched_at = datetime.now()

    # ------------------------------------------------------------------- write cache
    if db_path:
        try:
            save_cache(db_path, ticker, raw, fetched_at)
            _logger.info("fundamentus_cache_write ticker=%s", ticker)
        except Exception as e:
            _logger.warning("fundamentus_cache_write_error ticker=%s error=%s", ticker, str(e))

    return {"text": _format(ticker, df), "indicators": raw, "fetched_at": fetched_at.isoformat()}


def get_complementary_data(ticker: str, db_path: Optional[str] = None,
                           ttl_seconds: int = 86400) -> str:
    """Mantem a interface textual do relatorio legado."""
    return get_complementary_payload(ticker, db_path=db_path, ttl_seconds=ttl_seconds)["text"]
