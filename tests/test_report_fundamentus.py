"""Testes para src/b3_report/sources/fundamentus.py (pynvest)."""
import math
from unittest.mock import patch
import pandas as pd
import pytest

from b3_report.sources.fundamentus import get_complementary_data

_FAKE_ROW = {
    "nome_empresa": "PETROBRAS S.A.",
    "nome_setor": "Petróleo e Gás",
    "nome_subsetor": "Exploração e Produção",
    "vlr_cot": 49.41,
    "dt_ult_cot": "28/03/2026",
    "vlr_min_52_sem": 30.10,
    "vlr_max_52_sem": 49.44,
    "vol_med_neg_2m": 98765432.0,
    "vlr_mercado": 636800000000.0,
    "vlr_firma": 700000000000.0,
    "num_acoes": 13000000000,
    "dt_ult_balanco_proc": "31/12/2024",
    "vlr_ind_p_sobre_l": 6.05,
    "vlr_ind_p_sobre_vp": 1.20,
    "vlr_ind_p_sobre_ebit": 4.10,
    "vlr_ind_psr": 0.90,
    "vlr_ind_p_sobre_ativ": 0.50,
    "vlr_ind_p_sobre_cap_giro": math.nan,
    "vlr_ind_p_sobre_ativ_circ_liq": math.nan,
    "vlr_ind_ev_sobre_ebitda": 3.50,
    "vlr_ind_ev_sobre_ebit": 4.80,
    "vlr_ind_div_yield": 0.0791,
    "vlr_ind_lpa": 8.16,
    "vlr_ind_vpa": 41.00,
    "vlr_ind_roe": 0.20,
    "vlr_ind_roic": 0.15,
    "vlr_ind_margem_bruta": 0.45,
    "vlr_ind_margem_ebit": 0.30,
    "vlr_ind_margem_liq": 0.15,
    "vlr_ind_ebit_sobre_ativo": 0.12,
    "vlr_ind_giro_ativos": 0.35,
    "pct_cresc_rec_liq_ult_5a": 0.08,
    "vlr_ativo": 900000000000.0,
    "vlr_disponibilidades": 50000000000.0,
    "vlr_ativ_circulante": 150000000000.0,
    "vlr_divida_bruta": 300000000000.0,
    "vlr_divida_liq": 250000000000.0,
    "vlr_patrim_liq": 367510000000.0,
    "vlr_liquidez_corr": 1.20,
    "vlr_ind_divida_bruta_sobre_patrim": 0.82,
    "vlr_receita_liq_ult_12m": 500000000000.0,
    "vlr_ebit_ult_12m": 150000000000.0,
    "vlr_lucro_liq_ult_12m": 75000000000.0,
    "vlr_receita_liq_ult_3m": 120000000000.0,
    "vlr_ebit_ult_3m": 35000000000.0,
    "vlr_lucro_liq_ult_3m": 18000000000.0,
    "pct_var_dia": 0.01,
    "pct_var_mes": 0.03,
    "pct_var_30d": 0.05,
    "pct_var_12m": 0.12,
    "pct_var_ano_a0": 0.08,
    "pct_var_ano_a1": -0.05,
    "pct_var_ano_a2": 0.20,
}

_FAKE_DF = pd.DataFrame([_FAKE_ROW])

_PATCH_TARGET = "b3_report.sources.fundamentus.Fundamentus"


def test_get_complementary_data_retorna_texto():
    """Com DataFrame válido, retorna string com ticker e seções esperadas."""
    with patch(_PATCH_TARGET) as mock_cls:
        mock_cls.return_value.coleta_indicadores_de_ativo.return_value = _FAKE_DF
        result = get_complementary_data("PETR4")
    assert "PETR4" in result
    assert "Dados de Mercado" in result
    assert "Múltiplos de Valuation" in result
    assert "Rentabilidade" in result
    assert "Balanço e DRE (Fundamentus)" in result
    assert "Oscilações" in result
    assert "PETROBRAS S.A." in result
    assert "6.05" in result


def test_get_complementary_data_omite_nan():
    """Colunas com NaN não aparecem na saída."""
    with patch(_PATCH_TARGET) as mock_cls:
        mock_cls.return_value.coleta_indicadores_de_ativo.return_value = _FAKE_DF
        result = get_complementary_data("PETR4")
    assert "P/Cap.Giro" not in result
    assert "P/Ativ.Circ.Liq" not in result


def test_get_complementary_data_excecao():
    """Exception no pynvest → retorna '' sem propagar."""
    with patch(_PATCH_TARGET) as mock_cls:
        mock_cls.return_value.coleta_indicadores_de_ativo.side_effect = Exception("timeout")
        result = get_complementary_data("PETR4")
    assert result == ""


def test_get_complementary_data_df_vazio():
    """DataFrame vazio → retorna ''."""
    with patch(_PATCH_TARGET) as mock_cls:
        mock_cls.return_value.coleta_indicadores_de_ativo.return_value = pd.DataFrame()
        result = get_complementary_data("PETR4")
    assert result == ""
