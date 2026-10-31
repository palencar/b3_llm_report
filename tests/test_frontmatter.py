from copy import deepcopy
import json

import pytest

from b3_report.assessment import HORIZONS, INVESTMENT_CLASSES, RISK_CLASSES, SCHEMA_VERSION
from b3_report.frontmatter import format_frontmatter, report_frontmatter


@pytest.fixture
def result():
    def classified(choice, classes):
        return {"status": "classificado", "class": choice}
    return {
        "schema_version": SCHEMA_VERSION, "ticker": "WEGE3", "analysis_date": "2026-10-31",
        "model": "modelo-simulado", "dataset_id": "snapshot-simulado",
        "rubric_version": "rubrica-simulada", "instructions_version": "instrucoes-simuladas",
        "horizons": {h: {"investment": classified("Compra", INVESTMENT_CLASSES),
                         "risk": {**classified("Moderado", RISK_CLASSES), "direction": "comprada"}}
                     for h in HORIZONS},
    }


def test_metadados_essenciais_em_portugues_sem_dados_tecnicos(result):
    result["stages"] = [{"prompt": "NAO_PUBLICAR", "response": "NAO_PUBLICAR"}]
    result["event_context"] = {"debug": "NAO_PUBLICAR"}
    result["horizons"]["curto"]["investment"]["relatorio"] = "NAO_PUBLICAR"
    result["horizons"]["curto"]["investment"]["extra"] = "NAO_PUBLICAR"
    before = deepcopy(result)
    metadata = report_frontmatter(result)
    assert metadata == {
        "simbolo": "WEGE3", "data_analise": "2026-10-31", "modelo": "modelo-simulado",
        "horizontes": {h: {"investimento": {"estado": "classificado", "classe": "Compra"},
                           "risco": {"estado": "classificado", "classe": "Moderado", "direcao": "comprada"}}
                       for h in HORIZONS},
    }
    assert "NAO_PUBLICAR" not in format_frontmatter(result)
    metadata["horizontes"]["curto"]["investimento"]["classe"] = "Venda"
    assert result == before


def test_serializacao_tem_delimitadores_e_ordem_estavel(result):
    text = format_frontmatter(result)
    assert text.startswith('---\nsimbolo: "WEGE3"\ndata_analise: "2026-10-31"\n')
    assert text.endswith("\n---")
    assert text.count("\n---") == 1
    assert text.index("curtissimo:") < text.index("curto:") < text.index("medio:")
    assert text == format_frontmatter(result)


def test_neutro_nao_recebe_classe_de_risco_ou_direcao(result):
    row = result["horizons"]["curto"]
    row["investment"]["class"] = "Neutro"
    row["risk"] = {"status": "nao_aplicavel", "reason": "Sem posicao."}
    metadata = report_frontmatter(result)["horizontes"]["curto"]
    assert metadata["investimento"] == {"estado": "classificado", "classe": "Neutro"}
    assert metadata["risco"] == {"estado": "nao_aplicavel"}


@pytest.mark.parametrize("status", ["erro", "dados_insuficientes"])
def test_motivo_propagado_nao_e_duplicado(result, status):
    row = result["horizons"]["curto"]
    reason = "financial_health: evidencia ausente ou sem valor valido."
    row["investment"] = {"status": status, "reason": reason}
    row["risk"] = {"status": status, "reason": f"Risco nao avaliado: investimento {status}. {reason}"}
    metadata = report_frontmatter(result)["horizontes"]["curto"]
    assert metadata["investimento"] == {"estado": status, "motivo": "faltam dados validos de saude financeira."}
    assert metadata["risco"] == {"estado": status}


def test_insuficiencia_de_risco_preserva_investimento_e_direcao(result):
    result["horizons"]["curto"]["risk"] = {
        "status": "dados_insuficientes", "direction": "comprada", "reason": "Evidencia incompleta."}
    row = report_frontmatter(result)["horizontes"]["curto"]
    assert row["investimento"]["classe"] == "Compra"
    assert row["risco"] == {"estado": "dados_insuficientes", "direcao": "comprada", "motivo": "Evidencia incompleta."}


@pytest.mark.parametrize("reason", ['Dado "invalido": ausente\n---\nchave: valor', "# &ancora: [valor]", "nulo: null"])
def test_motivos_sao_escapados_sem_injetar_chaves(result, reason):
    row = result["horizons"]["curto"]
    row["investment"] = {"status": "erro", "reason": reason}
    row["risk"] = {"status": "erro", "reason": f"Risco nao avaliado: investimento erro. {reason}"}
    text = format_frontmatter(result)
    line = next(line for line in text.splitlines() if "motivo:" in line)
    assert json.loads(line.split("motivo: ", 1)[1]) == reason
    assert text.count("\n---") == 1


def test_rejeita_resultado_incoerente_antes_de_publicar(result):
    result["horizons"]["curto"]["risk"]["direction"] = "vendida"
    with pytest.raises(ValueError, match="direcao do risco diverge"):
        format_frontmatter(result)


def test_legado_nao_publica_estimativas_e_nao_e_reescrito(result):
    current = format_frontmatter(result)
    result["schema_version"] = "assessment-v2"
    result["probability_source"] = "autodeclarada-nao-calibrada"
    for row in result["horizons"].values():
        for item in row.values():
            item.update(confidence=0.7, probabilities={item["class"]: 1.0})
    before = deepcopy(result)
    assert format_frontmatter(result) == current
    assert result == before


@pytest.mark.parametrize("field", ["probabilities", "confidence", "probability_source"])
def test_frontmatter_recusa_estimativas_em_resultado_novo(result, field):
    result["horizons"]["curto"]["investment"][field] = "removido"
    with pytest.raises(ValueError, match="nao sao aceitos"):
        format_frontmatter(result)
