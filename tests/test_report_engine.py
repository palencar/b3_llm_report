from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from b3_report.assessment import HORIZONS
from b3_report.snapshot import SNAPSHOT_VERSION, snapshot_id
from b3_report.llm import LLMRequestError
from b3_report.rubric import MAX_AGE_DAYS, build_investment_question, build_risk_question
from b3_report.frontmatter import report_frontmatter
from b3_report.report_engine import format_report_markdown
from b3_report.unified import build_unified_prompt, classify_unified_snapshot, parse_unified_answers


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
            "relatorio": "Fundamento simulado."}


def sender(choices, calls):
    def request(prompt):
        payload = json.loads(prompt.split("\n", 1)[1])
        calls.append(payload)
        return json.dumps({"answers": {h: answer(q, choices[len(calls) - 1][h])
                                       for h, q in payload["questions"].items()}})
    return request


def test_unificado_mesmo_snapshot_rubrica_e_duas_etapas(snapshot):
    before, calls = deepcopy(snapshot), []
    result = classify_unified_snapshot(snapshot, model="simulado", requester=sender([
        {"curtissimo": "Compra forte", "curto": "Neutro", "medio": "Compra"},
        {"curtissimo": "Alto", "medio": "Alto"},
    ], calls))
    assert calls[0]["state"] == snapshot
    assert calls[0]["questions"] == {h: build_investment_question(h) for h in HORIZONS}
    assert calls[1]["questions"] == {h: build_risk_question(h, "comprada") for h in ("curtissimo", "medio")}
    assert set(calls[1]["state"]) == {"snapshot", "risk_directions"}
    assert result["dataset_id"] == snapshot_id(snapshot)
    assert result["horizons"]["curto"]["risk"]["status"] == "nao_aplicavel"
    assert result["horizons"]["curtissimo"]["risk"]["class"] == "Alto"
    assert "probability_source" not in result
    assert format_report_markdown(result).startswith('---\nsimbolo: "WEGE3"\n')
    assert "Fundamento simulado." in format_report_markdown(result)
    assert snapshot == before


@pytest.mark.parametrize("horizon", HORIZONS)
@pytest.mark.parametrize("stage", ["investment", "risk"])
def test_prompt_preserva_ordem_dos_criterios(horizon, stage):
    question = (build_investment_question(horizon) if stage == "investment"
                else build_risk_question(horizon, "comprada"))
    payload = json.loads(build_unified_prompt({}, {horizon: question}).split("\n", 1)[1])
    assert list(payload["questions"][horizon]["criteria"]) == list(question["criteria"])


def test_relatorio_markdown_estrutura_e_conteudo(snapshot):
    calls = []
    result = classify_unified_snapshot(snapshot, model="simulado", requester=sender([
        {"curtissimo": "Compra forte", "curto": "Neutro", "medio": "Compra"},
        {"curtissimo": "Alto", "medio": "Alto"},
    ], calls))
    text = format_report_markdown(result)
    lines = text.splitlines()
    assert lines[0] == "---"
    assert "WEGE3 - 2026-10-12" in lines
    assert "# Relatorio de investimento - WEGE3" in lines
    assert "## Analise por horizonte" in lines
    assert "### Curtissimo prazo" in lines and "### Curto prazo" in lines and "### Medio prazo" in lines
    assert "- **Investimento:** Compra forte. Fundamento simulado." in text
    assert "- **Risco (comprada):** Alto. Fundamento simulado." in text
    assert "- **Risco:** Nao aplicavel: sem posicao." in text
    assert text.count("Neutro: encerrar eventual posicao") == 1
    assert text.index("## Resumo") < text.index("## Analise por horizonte")
    assert "| Curtissimo prazo | Compra forte | Comprada | Alto |" in text
    assert "| Curto prazo | Neutro | Sem posicao | Nao aplicavel |" in text
    assert "Modelo: simulado" in lines
    assert "Rubrica:" not in text and "Instrucoes:" not in text
    assert "Snapshot:" not in text and "Apresentacao:" not in text
    assert "<details>" not in text and "<summary>" not in text
    assert result["presentation_version"] == "relatorio-markdown-v7-aviso-experimental"
    assert text.count("> Aviso: projeto experimental.") == 1
    assert text.index("> Aviso: projeto experimental.") < text.index("## Resumo")
    assert "nao constitui recomendacao de investimento nem orientacao financeira personalizada." in text
    assert not any(line.startswith("curtissimo:") for line in lines)




@pytest.mark.parametrize("choices", [
    ("Neutro", "Neutro", "Neutro"),
    ("Compra", "Compra", "Compra"),
    ("Venda", "Venda", "Venda"),
    ("Compra", "Neutro", "Venda"),
])
def test_avisos_contextuais_e_neutro_sem_repeticao(snapshot, choices):
    investments = dict(zip(HORIZONS, choices))
    risks = {h: "Moderado" for h in HORIZONS if investments[h] != "Neutro"}
    result = classify_unified_snapshot(snapshot, model="simulado",
                                      requester=sender([investments, risks], []))
    before = deepcopy(result)
    text = format_report_markdown(result)
    assert ("Risco qualitativo da posicao hipotetica" in text) == bool(risks)
    assert ("custos efetivos de aluguel" in text) == ("Venda" in choices)
    assert text.count("Neutro: encerrar eventual posicao") == int("Neutro" in choices)
    assert text.count("Nao aplicavel: sem posicao.") == choices.count("Neutro")
    assert "custos efetivos de aluguel" in result["risk_scope"]
    for h in HORIZONS:
        if investments[h] == "Neutro":
            assert result["horizons"][h]["risk"]["reason"] == (
                "Neutro: encerrar eventual posicao e ficar sem posicao no horizonte.")
    assert result == before


@pytest.mark.parametrize("failure", [False, True])
def test_aviso_presente_em_insuficiencia_e_erro_sem_alterar_dados(snapshot, failure):
    if not failure:
        snapshot["evidence"] = {}
    result = classify_unified_snapshot(snapshot, model="simulado",
        requester=Mock(side_effect=LLMRequestError("Falha simulada.")))
    before = deepcopy(result)
    text = format_report_markdown(result)
    assert text.count("> Aviso: projeto experimental.") == 1
    assert result == before
    assert "Aviso" not in json.dumps(report_frontmatter(result))


def test_relatorio_markdown_deterministico(snapshot):
    calls = []
    result = classify_unified_snapshot(snapshot, model="simulado", requester=sender([
        {"curtissimo": "Compra", "curto": "Compra", "medio": "Compra"},
        {"curtissimo": "Baixo", "curto": "Baixo", "medio": "Baixo"},
    ], calls))
    assert format_report_markdown(result) == format_report_markdown(result)


def test_resultado_antigo_com_rationale_continua_legivel_sem_reescrita(snapshot):
    result = classify_unified_snapshot(snapshot, model="simulado", requester=sender([
        {h: "Compra" for h in HORIZONS}, {h: "Moderado" for h in HORIZONS},
    ], []))
    markdown = format_report_markdown(result)
    result["schema_version"] = "assessment-v2"
    for row in result["horizons"].values():
        for item in row.values():
            item["rationale"] = item.pop("relatorio")
    before = deepcopy(result)
    assert format_report_markdown(result) == markdown
    assert result == before


def test_frontmatter_contem_somente_avaliacao_do_alerta(snapshot):
    result = classify_unified_snapshot(snapshot, model="simulado", requester=sender([
        {h: "Compra" for h in HORIZONS}, {h: "Moderado" for h in HORIZONS},
    ], []))
    result["debug"] = "MARCADOR_TECNICO"
    result["stages"][0]["debug"] = "MARCADOR_TECNICO"
    result["horizons"]["curto"]["investment"]["debug"] = "MARCADOR_TECNICO"
    before = deepcopy(result)
    summary = report_frontmatter(result)
    assert set(summary) == {"simbolo", "data_analise", "modelo", "horizontes"}
    assert summary["horizontes"]["curtissimo"] == {
        "investimento": {"estado": "classificado", "classe": "Compra"},
        "risco": {"estado": "classificado", "classe": "Moderado", "direcao": "comprada"}}
    assert "MARCADOR_TECNICO" not in json.dumps(summary)
    assert result == before
    summary["horizontes"]["curtissimo"]["investimento"]["classe"] = "Venda"
    assert result == before


@pytest.mark.parametrize("interval,divergent", [(False, False), (True, False), (True, True)])
def test_frontmatter_nao_duplica_eventos_do_corpo(snapshot, interval, divergent):
    result = classify_unified_snapshot(snapshot, model="simulado", requester=sender([
        {h: "Neutro" for h in HORIZONS},
    ], []))
    event = {"type": "resultados", "event_date": "2026-10-21", "event_time": None,
             "timezone": "UTC", "phase": "datas_divergentes_verificacao_pendente" if divergent else "evento_proximo",
             "certainty": "estimativa", "incorporation": "nao_verificado", "source": "Yahoo Finance",
             "origin": "yahoo-info", "id": "id-interno", "checked_at": "2026-10-12T10:00:00+00:00",
             "available_at": "2026-10-12T10:00:00+00:00", "provider_start_at": "2026-10-21T20:00:00+00:00",
             "provider_end_at": "2026-10-22T20:00:00+00:00" if interval else "2026-10-21T20:00:00+00:00",
             "provider_point_at": "2026-10-20T20:00:00+00:00" if divergent else None}
    result["event_context"] = {"as_of": "2026-10-12T10:00:00+00:00", "coverage": "parcial",
                               "events": [event], "policy_version": "interna"}
    before = deepcopy(result)
    summary = report_frontmatter(result)
    assert "event_context" not in summary
    text = format_report_markdown(result)
    assert "## Eventos corporativos" in text
    assert 'estado: "nao_aplicavel"' in text
    assert "confidence:" not in text and "probabilities:" not in text
    assert result == before


def test_frontmatter_preserva_motivos_sem_injetar_chaves(snapshot):
    result = classify_unified_snapshot(snapshot, model="simulado", requester=lambda p: "{}")
    item = result["horizons"]["curtissimo"]["investment"]
    item["reason"] = 'Dado "invalido": ausente\n---\nchave: valor'
    result["horizons"]["curtissimo"]["risk"]["reason"] = (
        "Risco nao avaliado: investimento erro. " + item["reason"])
    before = deepcopy(result)
    metadata = report_frontmatter(result)
    row = metadata["horizontes"]["curtissimo"]
    assert row["investimento"] == {"estado": "erro", "motivo": item["reason"]}
    assert row["risco"] == {"estado": "erro"}
    text = format_report_markdown(result)
    frontmatter = text.split("\n---\n", 1)[0]
    reason_line = next(line for line in frontmatter.splitlines() if "motivo:" in line)
    assert json.loads(reason_line.split("motivo: ", 1)[1]) == item["reason"]
    assert "\nchave:" not in frontmatter
    assert "classe:" not in frontmatter
    assert result == before


def test_prompt_preserva_ordens_recebidas_sem_reordenar(snapshot):
    questions = {h: build_investment_question(h) for h in reversed(HORIZONS)}
    for question in questions.values():
        question["criteria"] = dict(reversed(list(question["criteria"].items())))
    before = deepcopy(questions)
    payload = json.loads(build_unified_prompt(snapshot, questions).split("\n", 1)[1])
    assert list(payload["questions"]) == list(questions)
    for horizon in questions:
        assert list(payload["questions"][horizon]["criteria"]) == list(questions[horizon]["criteria"])
    assert questions == before


def test_dados_insuficientes_sem_chamada(snapshot):
    snapshot["evidence"] = {}
    request = Mock(side_effect=AssertionError("Nao chamar modelo."))
    result = classify_unified_snapshot(snapshot, model="simulado", requester=request)
    request.assert_not_called()
    assert result["stages"] == []
    assert all(row["investment"]["status"] == row["risk"]["status"] == "dados_insuficientes"
               for row in result["horizons"].values())


@pytest.mark.parametrize("reason,readable", [
    ("adverse_scenario: evidencia ausente ou sem valor valido.", "faltam dados validos de cenario adverso"),
    ("profitability: dado excede limite de 180 dias.", "rentabilidade: dado excede limite de 180 dias"),
    ("financial_health: data do dado ou de disponibilidade ausente/invalida.",
     "saude financeira: data do dado ou de disponibilidade ausente/invalida"),
    ("borrow_cost: fonte ausente; borrow_terms: evidencia ausente ou sem valor valido.",
     "custo de aluguel: fonte ausente; faltam dados validos de condicoes de aluguel"),
    ("Motivo novo informado pela fonte.", "Motivo novo informado pela fonte."),
])
def test_motivos_legiveis_sem_modificar_json(snapshot, reason, readable):
    request = Mock(return_value=json.dumps({"answers": {
        h: {"status": "dados_insuficientes", "reason": reason} for h in HORIZONS}}))
    result = classify_unified_snapshot(snapshot, model="simulado", requester=request)
    before = deepcopy(result)
    text = format_report_markdown(result)
    assert readable in text
    assert "| Curtissimo prazo | Dados insuficientes | - | Dados insuficientes |" in text
    assert "Risco:** Nao avaliado: investimento com dados insuficientes; veja o motivo acima." in text
    assert result == before
    assert result["horizons"]["curto"]["investment"]["reason"] == reason


def test_resumo_distingue_erro_e_insuficiencia_de_risco(snapshot):
    failed = classify_unified_snapshot(snapshot, model="simulado",
                                       requester=Mock(side_effect=LLMRequestError("Falha simulada.")))
    text = format_report_markdown(failed)
    assert "| Curtissimo prazo | Erro | - | Erro |" in text
    assert "Erro na avaliacao: Falha simulada." in text
    calls = []
    snapshot["evidence"]["liquidity"]["value"] = None
    result = classify_unified_snapshot(snapshot, model="simulado",
                                      requester=sender([{h: "Venda" for h in HORIZONS}], calls))
    text = format_report_markdown(result)
    assert "| Curto prazo | Venda | Vendida | Dados insuficientes |" in text
    assert "faltam dados validos de liquidez" in text


def test_abstencao_explicita_bloqueia_risco(snapshot):
    request = Mock(return_value=json.dumps({"answers": {
        h: {"status": "dados_insuficientes", "reason": "Falta evidencia independente."} for h in HORIZONS}}))
    result = classify_unified_snapshot(snapshot, model="simulado", requester=request)
    assert request.call_count == 1
    assert all(row["risk"]["status"] == "dados_insuficientes" for row in result["horizons"].values())


def test_venda_sem_aluguel_e_cenario_classifica_risco(snapshot):
    calls = []
    snapshot["risk_evidence"] = {}
    result = classify_unified_snapshot(snapshot, model="simulado",
                                      requester=sender([{h: "Venda" for h in HORIZONS},
                                                        {h: "Alto" for h in HORIZONS}], calls))
    assert len(calls) == 2
    assert all(row["risk"]["class"] == "Alto" and row["risk"]["direction"] == "vendida"
               for row in result["horizons"].values())
    assert "nao confirma viabilidade" in format_report_markdown(result)


@pytest.mark.parametrize("error", [LLMRequestError("Falha simulada."), ValueError("JSON invalido.")])
def test_erro_primeira_etapa_sem_fallback(snapshot, error):
    request = Mock(side_effect=error)
    result = classify_unified_snapshot(snapshot, model="simulado", requester=request)
    assert request.call_count == 1
    assert all(row["investment"]["status"] == row["risk"]["status"] == "erro"
               for row in result["horizons"].values())


def test_erro_risco_preserva_investimento(snapshot):
    first = json.dumps({"answers": {h: answer(build_investment_question(h), "Compra") for h in HORIZONS}})
    result = classify_unified_snapshot(snapshot, model="simulado",
                                      requester=Mock(side_effect=[first, LLMRequestError("Falha risco.")]))
    assert all(row["investment"]["class"] == "Compra" and row["risk"]["status"] == "erro"
               for row in result["horizons"].values())


@pytest.mark.parametrize("text", ["", "```json\n{}\n```", '{"answers":{},"answers":{}}',
                                  '{"answers":{}}', '{"answers":[],"extra":1}'])
def test_resposta_invalida_sem_reparo_silencioso(text):
    with pytest.raises(ValueError):
        parse_unified_answers(text, {"curto": build_investment_question("curto")})


def test_exige_fundamento_e_recusa_metadados_removidos():
    question = build_investment_question("curto")
    value = answer(question, "Compra")
    for change in ({"relatorio": ""}, {"confidence": float("nan")}, {"probabilities": {}}):
        with pytest.raises(ValueError):
            parse_unified_answers(json.dumps({"answers": {"curto": {**value, **change}}}), {"curto": question})


def test_prompt_deterministico_sem_mutacao(snapshot):
    before = deepcopy(snapshot)
    questions = {"curto": build_investment_question("curto")}
    assert build_unified_prompt(snapshot, questions) == build_unified_prompt(snapshot, questions)
    assert snapshot == before


def test_sem_chamador_padrao(snapshot):
    with pytest.raises(TypeError):
        classify_unified_snapshot(snapshot, model="simulado")
    with pytest.raises(ValueError):
        classify_unified_snapshot(snapshot, model="simulado", requester=None)


@pytest.mark.parametrize("stage", ["investment", "risk"])
def test_esquema_de_formato_preserva_perguntas_sem_sugerir_classe(snapshot, stage):
    questions = {h: (build_investment_question(h) if stage == "investment"
                     else build_risk_question(h, "comprada")) for h in reversed(HORIZONS)}
    prompt = build_unified_prompt(snapshot, questions)
    payload = json.loads(prompt.split("\n", 1)[1])
    assert payload["state"] == snapshot
    assert payload["questions"] == questions
    schema = payload["response_schema"]
    assert schema["required"] == ["answers"]
    assert schema["additionalProperties"] is False
    answers = schema["properties"]["answers"]
    assert answers["required"] == list(questions)
    for horizon, question in questions.items():
        classified, insufficient = answers["properties"][horizon]["oneOf"]
        assert classified["properties"]["status"] == {"const": "classificado"}
        assert classified["properties"]["class"]["enum"] == list(question["criteria"])
        assert set(classified["properties"]) == {"status", "class", "relatorio"}
        assert set(classified["required"]) == {"status", "class", "relatorio"}
        assert insufficient["properties"]["status"] == {"const": "dados_insuficientes"}
        assert insufficient["required"] == ["status", "reason"]
        assert classified["additionalProperties"] is insufficient["additionalProperties"] is False
    assert '"status": "classificado"' in prompt


def test_status_classified_reproduz_falha_sem_correcao_ou_retry(snapshot):
    original = {"answers": {h: {**answer(build_investment_question(h), "Compra"),
                              "status": "classified"} for h in HORIZONS}}
    response = json.dumps(original)
    request = Mock(return_value=response)
    result = classify_unified_snapshot(snapshot, model="simulado", requester=request)
    request.assert_called_once()
    assert result["stages"][0]["response"] == response
    assert all(row["investment"]["status"] == row["risk"]["status"] == "erro"
               for row in result["horizons"].values())
    assert 'literal "classificado"' in result["stages"][0]["error"]
    assert original["answers"]["curtissimo"]["status"] == "classified"
