from copy import deepcopy
from datetime import date, timedelta

import pytest

from b3_report.assessment import HORIZONS, INVESTMENT_CLASSES, RISK_CLASSES
from b3_report.rubric import (
    MAX_AGE_DAYS, RISK_CRITERIA, RUBRIC_VERSION, build_investment_question, build_risk_question, check_data_readiness,
)


@pytest.fixture
def evidence():
    result = {key: {"value": 1.0, "source": "fixture", "as_of": "2026-10-12",
                    "available_at": "2026-10-12", "conflict": False} for key in MAX_AGE_DAYS}
    result["adverse_scenario"]["value"] = {
        "direction": "vendida", "horizon": "curto", "loss_basis": "initial_exposure",
        "loss_fraction": 0.3, "description": "Cenario adverso simulado.",
    }
    result["borrow_availability"]["value"] = True
    result["borrow_cost"]["value"] = 0.0
    result["borrow_terms"]["value"] = "Condicoes simuladas."
    return result


@pytest.mark.parametrize("horizon", HORIZONS)
def test_investimento_com_dados_completos_sem_mutacao(evidence, horizon):
    before = deepcopy(evidence)
    assert check_data_readiness(evidence, analysis_date="2026-10-12", horizon=horizon) == {"status": "pronto"}
    assert evidence == before


def test_exigencias_diferem_por_horizonte(evidence):
    del evidence["growth"]
    assert check_data_readiness(evidence, analysis_date="2026-10-12", horizon="curto")["status"] == "pronto"
    result = check_data_readiness(evidence, analysis_date="2026-10-12", horizon="medio")
    assert result["status"] == "dados_insuficientes" and "growth" in result["reason"]


def test_cache_recente_nao_rejuvenesce_fundamentos(evidence):
    evidence["profitability"]["as_of"] = "2025-01-01"
    result = check_data_readiness(evidence, analysis_date="2026-10-12", horizon="curto")
    assert result["status"] == "dados_insuficientes" and "180 dias" in result["reason"]


@pytest.mark.parametrize("offset,status", [(7, "pronto"), (8, "dados_insuficientes")])
def test_limite_de_atualidade_inclusivo(evidence, offset, status):
    evidence["price"]["as_of"] = (date(2026, 10, 12) - timedelta(days=offset)).isoformat()
    assert check_data_readiness(evidence, analysis_date="2026-10-12", horizon="curto")["status"] == status


def test_rejeita_evidencia_nao_disponivel_na_data_de_referencia(evidence):
    evidence["valuation"]["available_at"] = "2026-10-13"
    assert check_data_readiness(evidence, analysis_date="2026-10-12", horizon="curto")["status"] == "dados_insuficientes"


@pytest.mark.parametrize("field,value", [("source", ""), ("as_of", None), ("value", float("nan")), ("conflict", True)])
def test_motivo_de_insuficiencia_explicito(evidence, field, value):
    evidence["price"][field] = value
    result = check_data_readiness(evidence, analysis_date="2026-10-12", horizon="curto")
    assert result["status"] == "dados_insuficientes" and "price" in result["reason"]


def test_aluguel_ausente_nao_bloqueia_risco_vendido(evidence):
    del evidence["borrow_availability"]
    assert check_data_readiness(evidence, analysis_date="2026-10-12", horizon="curto")["status"] == "pronto"
    risk = check_data_readiness(evidence, analysis_date="2026-10-12", horizon="curto", direction="vendida")
    assert risk["status"] == "pronto"


def test_risco_comprado_nao_exige_aluguel(evidence):
    for key in ("borrow_availability", "borrow_cost", "borrow_terms"):
        del evidence[key]
    evidence["adverse_scenario"]["value"]["direction"] = "comprada"
    assert check_data_readiness(evidence, analysis_date="2026-10-12", horizon="curto", direction="comprada")["status"] == "pronto"


def test_cenario_opcional_de_direcao_contraria_nao_define_suficiencia(evidence):
    risk = check_data_readiness(evidence, analysis_date="2026-10-12", horizon="curto", direction="comprada")
    assert risk["status"] == "pronto"
    assert "outra direcao" in build_risk_question("curto", "comprada")["instructions"]


@pytest.mark.parametrize("horizon", HORIZONS)
def test_perguntas_usam_mesmas_classes_e_condicoes(horizon):
    investment = build_investment_question(horizon)
    risk = build_risk_question(horizon, "vendida")
    assert tuple(investment["criteria"]) == INVESTMENT_CLASSES
    assert tuple(risk["criteria"]) == RISK_CLASSES
    assert "sem alavancagem" in investment["instructions"] and "sem alavancagem" in risk["instructions"]
    assert "posicao vendida" in risk["instructions"]
    investment["criteria"]["Compra"] = "Nao compartilhar estado mutavel."
    assert build_investment_question(horizon)["criteria"]["Compra"] != investment["criteria"]["Compra"]


def test_pergunta_de_risco_nao_inventa_direcao():
    with pytest.raises(ValueError):
        build_risk_question("curto", "neutra")


@pytest.mark.parametrize("value", [False, True, 0, -1, {"valor": None}, 10**1000])
def test_cotacao_invalida_nao_e_evidencia_suficiente(evidence, value):
    evidence["price"]["value"] = value
    assert check_data_readiness(evidence, analysis_date="2026-10-12", horizon="curto")["status"] == "dados_insuficientes"


def test_cenario_opcional_de_outro_horizonte_nao_bloqueia(evidence):
    risk = check_data_readiness(evidence, analysis_date="2026-10-12", horizon="medio", direction="vendida")
    assert risk["status"] == "pronto"


def test_aluguel_indisponivel_e_limitacao_operacional_nao_insuficiencia(evidence):
    evidence["borrow_availability"]["value"] = False
    risk = check_data_readiness(evidence, analysis_date="2026-10-12", horizon="curto", direction="vendida")
    assert risk["status"] == "pronto"


@pytest.mark.parametrize("horizon", HORIZONS)
@pytest.mark.parametrize("direction", ["comprada", "vendida"])
def test_risco_qualitativo_sem_cenario_aluguel_ou_noticias(evidence, horizon, direction):
    evidence = {key: value for key, value in evidence.items() if key in ("price", "liquidity", "financial_health")}
    assert check_data_readiness(evidence, analysis_date="2026-10-12", horizon=horizon,
                                direction=direction) == {"status": "pronto"}
    question = build_risk_question(horizon, direction)
    assert "nao confirma viabilidade" in question["instructions"]
    assert "Nao transforme taxa media em disponibilidade confirmada" in question["instructions"]
    assert "qualitativamente" in question["instructions"]
    assert "10%" not in str(question) and "25%" not in str(question)


@pytest.mark.parametrize("key", ["price", "liquidity", "financial_health"])
@pytest.mark.parametrize("direction", ["comprada", "vendida"])
@pytest.mark.parametrize("change", ["missing", "stale", "future", "conflict", "empty"])
def test_dados_essenciais_de_risco_ainda_sao_exigidos(evidence, key, direction, change):
    if change == "missing":
        del evidence[key]
    elif change == "stale":
        evidence[key]["as_of"] = "2020-01-01"
    elif change == "future":
        evidence[key]["available_at"] = "2026-10-13"
    elif change == "conflict":
        evidence[key]["conflict"] = True
    else:
        evidence[key]["value"] = None
    result = check_data_readiness(evidence, analysis_date="2026-10-12", horizon="curto", direction=direction)
    assert result["status"] == "dados_insuficientes" and key in result["reason"]


def test_criterios_qualitativos_nao_confundem_ausencia_com_baixo_risco():
    assert "v2" in RUBRIC_VERSION
    assert "Evidencias afirmativas" in RISK_CRITERIA["Baixo"]
    assert "Nao basta ausencia" in RISK_CRITERIA["Baixo"]
    assert "Fatores adversos materiais" in RISK_CRITERIA["Moderado"]
    assert "fator severo sustentado" in RISK_CRITERIA["Alto"]


@pytest.mark.parametrize("horizon", HORIZONS)
def test_procedencia_e_precificacao_nas_duas_perguntas(horizon):
    for question in (build_investment_question(horizon), build_risk_question(horizon, "comprada"),
                     build_risk_question(horizon, "vendida")):
        instructions = question["instructions"]
        assert "fonte e periodo dos indicadores materiais" in instructions
        assert "indicador, unidade, periodo e base de calculo" in instructions
        assert "Periodos distintos nao demonstram contradicao por si so" in instructions
        assert "mesma fonte e periodo" in instructions
        assert "Se a base nao estiver explicitada" in instructions
        assert "fonte primaria declarada no grupo normalizado" in instructions
        assert "Nao faca media nem escolha silenciosamente" in instructions
        assert "nao e precificacao pelo mercado" in instructions
        assert "sem evidencia explicita de precificacao" in instructions


@pytest.mark.parametrize("horizon", HORIZONS)
@pytest.mark.parametrize("direction", ["comprada", "vendida"])
def test_instrucao_de_risco_exige_mecanismo_da_direcao_sem_novos_campos(horizon, direction):
    question = build_risk_question(horizon, direction)
    assert set(question) == {"type", "instructions", "criteria"}
    assert question["criteria"] == RISK_CRITERIA
    text = question["instructions"]
    assert "A comprada perde com queda do preco; a vendida perde com alta do preco" in text
    assert "mecanismo de perda ou dificuldade de saida" in text
    assert "nao demonstram sozinhos risco Alto" in text
    assert "nem impede sua reducao" in text
    assert "condicao obrigatoria de revisao" in text
    assert "contraponto deve limitar a conclusao de risco" in text


def test_instrucao_nao_combina_volumes_nem_presume_ausencia_de_eventos():
    for question in (build_investment_question("curto"), build_risk_question("curto", "vendida")):
        assert "volume em acoes nao e volume financeiro" in question["instructions"]
        assert "sem combinar valores" in question["instructions"]
        assert "nao prova ausencia de eventos" in question["instructions"]
