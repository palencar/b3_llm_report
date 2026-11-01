from copy import deepcopy
import json

import pytest
from b3_report.llm import LLMResponse

from b3_report.assessment import HORIZONS
from b3_report.decision_snapshot import SNAPSHOT_VERSION, snapshot_id
from b3_report.rubric import MAX_AGE_DAYS
from b3_report.textual_baseline import format_report_markdown
from b3_report.unified import (
    UNIFIED_FORMAT_VERSION, build_unified_prompt, classify_unified_snapshot,
    parse_unified_answers,
)


@pytest.fixture
def snapshot():
    def item(value):
        return {"value": value, "source": "simulada", "as_of": "2026-10-12",
                "available_at": "2026-10-12", "conflict": False}
    evidence = {key: item(1.0) for key in MAX_AGE_DAYS
                if key not in ("adverse_scenario", "borrow_availability", "borrow_cost", "borrow_terms")}
    risk = {h: {"comprada": {"adverse_scenario": item({
        "direction": "comprada", "horizon": h, "loss_basis": "initial_exposure",
        "loss_fraction": 0.3, "description": "Cenario simulado.",
    })}} for h in HORIZONS}
    return {"snapshot_version": SNAPSHOT_VERSION, "ticker": "WEGE3",
            "analysis_date": "2026-10-12", "evidence": evidence, "risk_evidence": risk,
            "source_data": {"yfinance": {}, "fundamentus": "", "cvm": []}}


def answer(question, choice):
    return {"status": "classificado", "class": choice,
            "relatorio": "Relatorio simulado do horizonte."}


def sender(choices, calls):
    def request(prompt):
        payload = json.loads(prompt.split("\n", 1)[1])
        calls.append(payload)
        return json.dumps({"answers": {h: answer(q, choices[len(calls) - 1][h])
                                       for h, q in payload["questions"].items()}})
    return request


def test_structured_output_envia_esquema_por_etapa_e_preserva_metadados(snapshot):
    calls = []
    def request(prompt, *, response_schema):
        payload = json.loads(prompt.split("\n", 1)[1])
        calls.append(response_schema)
        questions = payload["questions"]
        assert response_schema["properties"]["answers"]["required"] == list(questions)
        for h in questions:
            classified = response_schema["properties"]["answers"]["properties"][h]["anyOf"][0]
            assert "relatorio" in classified["required"]
            assert classified["properties"]["status"]["enum"] == ["classificado"]
        choice = "Compra" if len(calls) == 1 else "Alto"
        return LLMResponse(json.dumps({"answers": {h: answer(q, choice) for h, q in questions.items()}}),
                           {"done": True, "done_reason": "stop", "eval_count": 20})
    result = classify_unified_snapshot(snapshot, model="simulado", requester=request, structured_output=True)
    assert len(calls) == 2
    assert result["structured_output"] == "on"
    for stage, schema in zip(result["stages"], calls):
        assert stage["response_schema"] == schema
        assert stage["response_metadata"]["done_reason"] == "stop"


@pytest.mark.parametrize("metadata", [{"done": True, "done_reason": "length", "eval_count": 50},
                                      {"finish_reason": "length"}, {"done": False}])
def test_encerramento_incompleto_preserva_resposta_sem_retry(snapshot, metadata):
    calls = []
    def request(prompt):
        calls.append(prompt)
        return LLMResponse('{"answers":', metadata)
    result = classify_unified_snapshot(snapshot, model="simulado", requester=request)
    assert len(calls) == 1
    stage = result["stages"][0]
    assert stage["response"] == '{"answers":'
    assert stage["response_metadata"] == metadata
    assert "Geracao incompleta" in stage["error"]
    assert all(row["investment"]["status"] == "erro" for row in result["horizons"].values())


def test_prompt_unificado_traz_relatorio_e_atributos_de_decisao(snapshot):
    prompt = build_unified_prompt(snapshot, {"curtissimo": {"criteria": ["Compra", "Neutro"]}})
    assert "relatorio" in prompt
    assert "atributos de decisao" in prompt
    payload = json.loads(prompt.split("\n", 1)[1])
    schema = payload["response_schema"]["properties"]["answers"]["properties"]["curtissimo"]
    fields = schema["oneOf"][0]["properties"]
    assert "relatorio" in fields
    assert set(fields) == {"status", "class", "relatorio"}
    assert "probabilities" not in prompt and "confidence" not in prompt


def test_prompt_conciso_preserva_entrada_e_contrato_atual(snapshot):
    questions = {"curtissimo": {"criteria": ["Compra", "Neutro"]}}
    before = deepcopy((snapshot, questions))
    proposal = build_unified_prompt(snapshot, questions)
    assert "2 a 4 frases" not in proposal
    assert "ate 3 frases curtas" in proposal
    assert "ate 90 palavras" in proposal
    assert "Fundamento:" in proposal and "Contraponto:" in proposal and "Revisao:" in proposal
    assert "sem inventar fatos, cenarios, metas ou gatilhos" in proposal
    assert "sem omitir fatores materiais" in proposal
    assert "nao adicionam requisitos de suficiencia" in proposal
    payload = json.loads(proposal.split("\n", 1)[1])
    assert payload["state"] == snapshot
    assert payload["questions"] == questions
    fields = payload["response_schema"]["properties"]["answers"]["properties"]["curtissimo"]["oneOf"][0]
    assert set(fields["required"]) == {"status", "class", "relatorio"}
    assert (snapshot, questions) == before


def test_prompt_nao_aceita_selecao_de_versao(snapshot):
    with pytest.raises(TypeError, match="format_version"):
        build_unified_prompt(snapshot, {}, format_version="desconhecida")


def test_parse_unificado_recusa_campo_narrativo_errado():
    questions = {"curtissimo": {"criteria": ["Compra", "Neutro"]}}
    payload = {"answers": {"curtissimo": {"status": "classificado", "class": "Compra",
                                          "rationale": "campo trocado"}}}
    with pytest.raises(ValueError):
        parse_unified_answers(json.dumps(payload), questions)


@pytest.mark.parametrize("change", [{"relatorio": " "}, {"relatorio": None}, {"class": "Hold"}])
def test_contrato_unico_valida_classe_e_justificativa(snapshot, change):
    calls = []
    def request(prompt):
        payload = json.loads(prompt.split("\n", 1)[1])
        calls.append(payload)
        return json.dumps({"answers": {h: {**answer(q, "Compra"), **change}
                                       for h, q in payload["questions"].items()}})
    result = classify_unified_snapshot(snapshot, model="simulado", requester=request)
    assert len(calls) == 1
    assert all(row["investment"]["status"] == row["risk"]["status"] == "erro"
               for row in result["horizons"].values())


@pytest.mark.parametrize("field", ["probabilities", "confidence", "probability_source"])
def test_resposta_com_estimativas_removidas_falha_sem_retry(snapshot, field):
    calls = []
    def request(prompt):
        payload = json.loads(prompt.split("\n", 1)[1])
        calls.append(payload)
        return json.dumps({"answers": {h: {**answer(q, "Compra"), field: "removido"}
                                       for h, q in payload["questions"].items()}})
    result = classify_unified_snapshot(snapshot, model="simulado", requester=request)
    assert len(calls) == 1
    assert all(row["investment"]["status"] == row["risk"]["status"] == "erro"
               for row in result["horizons"].values())


def test_classificacao_unificada_une_relatorio_e_decisao(snapshot):
    before, calls = deepcopy(snapshot), []
    result = classify_unified_snapshot(snapshot, model="simulado", requester=sender([
        {"curtissimo": "Compra forte", "curto": "Neutro", "medio": "Compra"},
        {"curtissimo": "Alto", "medio": "Alto"},
    ], calls))
    assert calls[0]["state"] == snapshot
    assert result["baseline_format_version"] == UNIFIED_FORMAT_VERSION
    assert result["dataset_id"] == snapshot_id(snapshot)
    assert result["horizons"]["curtissimo"]["investment"]["relatorio"] == "Relatorio simulado do horizonte."
    assert result["horizons"]["curto"]["risk"]["status"] == "nao_aplicavel"
    assert result["horizons"]["curtissimo"]["risk"]["class"] == "Alto"
    assert snapshot == before


def test_relatorio_unificado_renderiza_o_texto_do_modelo(snapshot):
    calls = []
    unified = classify_unified_snapshot(snapshot, model="simulado", requester=sender([
        {"curtissimo": "Compra forte", "curto": "Neutro", "medio": "Compra"},
        {"curtissimo": "Alto", "medio": "Alto"},
    ], calls))
    markdown = format_report_markdown(unified)
    assert markdown.startswith('---\nsimbolo: "WEGE3"\n')
    assert "- **Investimento:** Compra forte. Relatorio simulado do horizonte." in markdown
    assert unified["presentation_version"] == "relatorio-markdown-v6-frontmatter"
    assert "<details>" not in markdown and "<summary>" not in markdown
    assert "Snapshot:" not in markdown and "Rubrica:" not in markdown
