from copy import deepcopy

import pytest

from b3_report.assessment import (
    AssessmentValidationError, HORIZONS, INVESTMENT_CLASSES, RISK_CLASSES,
    SCHEMA_VERSION, prepare_risk_stage, validate_assessment_result,
)


def classified(label, classes):
    return {"status": "classificado", "class": label}


@pytest.fixture
def result():
    return {
        "schema_version": SCHEMA_VERSION, "ticker": "WEGE3",
        "analysis_date": "2026-10-12", "model": "modelo-simulado",
        "dataset_id": "fixture-01", "rubric_version": "proposta-01",
        "instructions_version": "fixture-01",
        "horizons": {h: {
            "investment": classified("Compra forte", INVESTMENT_CLASSES),
            "risk": {**classified("Alto", RISK_CLASSES), "direction": "comprada"},
        } for h in HORIZONS},
    }


def test_compra_forte_com_alto_risco_e_valida_sem_mutacao(result):
    before = deepcopy(result)
    validate_assessment_result(result)
    assert result == before


@pytest.mark.parametrize("kind", ["investment", "risk"])
@pytest.mark.parametrize("field", ["probabilities", "confidence", "probability_source"])
def test_novo_contrato_rejeita_metadados_removidos(result, kind, field):
    result["horizons"]["curto"][kind][field] = "campo removido"
    with pytest.raises(AssessmentValidationError, match="nao sao aceitos"):
        validate_assessment_result(result)


def test_novo_contrato_rejeita_origem_de_probabilidades(result):
    result["probability_source"] = "removida"
    with pytest.raises(AssessmentValidationError, match="nao e aceita"):
        validate_assessment_result(result)


def test_leitura_legada_nao_exige_nem_interpreta_estimativas(result):
    result["schema_version"] = "assessment-v2"
    result["probability_source"] = "autodeclarada-nao-calibrada"
    for row in result["horizons"].values():
        for item in row.values():
            item.update(confidence=0.7, probabilities={item["class"]: 1.0})
    before = deepcopy(result)
    validate_assessment_result(result)
    assert result == before


def test_venda_forte_com_alto_risco_e_valida(result):
    row = result["horizons"]["curto"]
    row["investment"] = classified("Venda forte", INVESTMENT_CLASSES)
    row["risk"]["direction"] = "vendida"
    validate_assessment_result(result)


def test_insuficiencia_de_risco_nao_apaga_investimento(result):
    result["horizons"]["medio"]["risk"] = {
        "status": "dados_insuficientes", "direction": "comprada",
        "reason": "Evidencias de perdas adversas ausentes.",
    }
    validate_assessment_result(result)
    assert result["horizons"]["medio"]["investment"]["class"] == "Compra forte"


def test_erro_de_investimento_nao_permite_presumir_direcao(result):
    result["horizons"]["curto"]["investment"] = {
        "status": "erro", "reason": "Resposta de investimento invalida.",
    }
    with pytest.raises(AssessmentValidationError, match="presumir direcao"):
        validate_assessment_result(result)
    result["horizons"]["curto"]["risk"] = {
        "status": "erro", "reason": "Investimento nao classificado.",
    }
    validate_assessment_result(result)


def test_rejeita_direcao_contraria_a_investimento(result):
    result["horizons"]["curto"]["risk"]["direction"] = "vendida"
    with pytest.raises(AssessmentValidationError, match="diverge"):
        validate_assessment_result(result)


@pytest.mark.parametrize("risk", [
    {"status": "erro"},
    {"status": "dados_insuficientes", "reason": " "},
    {"status": "erro", "reason": "Falha", "class": "Baixo"},
    {"status": "erro", "reason": "Falha", "probabilities": {}},
])
def test_rejeita_status_sem_motivo_ou_com_classificacao_inventada(result, risk):
    result["horizons"]["curto"]["risk"] = risk
    with pytest.raises(AssessmentValidationError):
        validate_assessment_result(result)


def test_risco_classificado_exige_direcao(result):
    del result["horizons"]["curto"]["risk"]["direction"]
    with pytest.raises(AssessmentValidationError, match="direcao obrigatoria"):
        validate_assessment_result(result)


def test_neutro_exige_risco_nao_aplicavel_sem_direcao(result):
    result["horizons"]["curto"]["investment"] = classified("Neutro", INVESTMENT_CLASSES)
    with pytest.raises(AssessmentValidationError, match="Neutro exige"):
        validate_assessment_result(result)
    result["horizons"]["curto"]["risk"] = {
        "status": "nao_aplicavel", "reason": "Sem posicao proposta.",
    }
    validate_assessment_result(result)


def test_prepara_segunda_etapa_apenas_para_direcoes_conhecidas(result):
    investments = {h: row["investment"] for h, row in result["horizons"].items()}
    investments["curto"] = classified("Venda forte", INVESTMENT_CLASSES)
    investments["medio"] = classified("Neutro", INVESTMENT_CLASSES)
    before = deepcopy(investments)
    directions, resolved = prepare_risk_stage(investments)
    assert directions == {"curtissimo": "comprada", "curto": "vendida"}
    assert set(resolved) == {"medio"}
    assert resolved["medio"]["status"] == "nao_aplicavel"
    assert investments == before


@pytest.mark.parametrize("status", ["erro", "dados_insuficientes"])
def test_investimentos_nao_classificados_nao_geram_perguntas_de_risco(status):
    investments = {h: {"status": status, "reason": "Motivo da primeira etapa."} for h in HORIZONS}
    directions, resolved = prepare_risk_stage(investments)
    assert directions == {}
    assert all(item["status"] == status and "direction" not in item for item in resolved.values())
    assert all("Motivo da primeira etapa." in item["reason"] for item in resolved.values())


@pytest.mark.parametrize("field", ["class", "probabilities", "confidence", "direction"])
def test_neutro_nao_aplicavel_nao_contem_classificacao_ou_direcao(result, field):
    row = result["horizons"]["curto"]
    row["investment"] = classified("Neutro", INVESTMENT_CLASSES)
    row["risk"] = {"status": "nao_aplicavel", "reason": "Sem posicao.", field: None}
    with pytest.raises(AssessmentValidationError):
        validate_assessment_result(result)


def test_nao_aplicavel_e_exclusivo_de_neutro(result):
    result["horizons"]["curto"]["risk"] = {"status": "nao_aplicavel", "reason": "Sem dados."}
    with pytest.raises(AssessmentValidationError, match="nao pode ser nao_aplicavel"):
        validate_assessment_result(result)


def test_investimento_nao_aceita_nao_aplicavel(result):
    result["horizons"]["curto"]["investment"] = {"status": "nao_aplicavel", "reason": "Ausente."}
    with pytest.raises(AssessmentValidationError, match="status invalido"):
        validate_assessment_result(result)


def test_exige_tres_horizontes(result):
    del result["horizons"]["medio"]
    with pytest.raises(AssessmentValidationError, match="exatamente"):
        validate_assessment_result(result)


def test_rejeita_data_inexistente(result):
    result["analysis_date"] = "2026-02-30"
    with pytest.raises(AssessmentValidationError, match="data inexistente"):
        validate_assessment_result(result)
