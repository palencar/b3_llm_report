"""Motor textual compartilhado e apresentacao do relatorio; sem cliente de rede."""

from copy import deepcopy

from b3_report.assessment import (
    HORIZONS, SCHEMA_VERSION, prepare_risk_stage,
    validate_assessment_result,
)
from b3_report.snapshot import snapshot_id, validate_snapshot
from b3_report.frontmatter import format_frontmatter, readable_reason as _readable_reason
from b3_report.llm import LLMError, LLMResponse, LLMResponseError
from b3_report.model_state import MODEL_STATE_VERSION
from b3_report.events import event_summary_lines, event_question
from b3_report.rubric import (
    HORIZON_DESCRIPTIONS, INSTRUCTIONS_VERSION, RUBRIC_VERSION, RISK_SCOPE_NOTE,
    RISK_QUALITATIVE_NOTE, SHORT_POSITION_NOTE, build_investment_question,
    build_risk_question, check_data_readiness,
)

# Identificador legado da configuracao persistida, nao uma segunda rota de geracao.
TEXT_FORMAT_VERSION = "baseline-textual-v4-sem-probabilidades"
REPORT_PRESENTATION_VERSION = "relatorio-markdown-v7-aviso-experimental"
HORIZON_TITLES = {"curtissimo": "Curtissimo prazo", "curto": "Curto prazo", "medio": "Medio prazo"}
_STATUS_TITLES = {"dados_insuficientes": "Dados insuficientes", "erro": "Erro",
                  "nao_aplicavel": "Nao aplicavel"}


def _unclassified_text(assessment: dict, investment: dict, label: str) -> str:
    status = assessment["status"]
    if label == "risk" and status == "nao_aplicavel":
        return "Nao aplicavel: sem posicao."
    # Evita repetir no risco o mesmo motivo ja apresentado no investimento.
    propagated = (f"Risco nao avaliado: investimento {investment['status']}. "
                  + investment.get("reason", ""))
    if label == "risk" and investment["status"] != "classificado" and assessment["reason"] == propagated:
        return "Nao avaliado: investimento com " + (
            "dados insuficientes" if investment["status"] == "dados_insuficientes" else "erro"
        ) + "; veja o motivo acima."
    prefix = {"dados_insuficientes": "Nao avaliado por dados insuficientes",
              "erro": "Erro na avaliacao", "nao_aplicavel": "Nao aplicavel"}[status]
    return f"{prefix}: {_readable_reason(assessment['reason'])}"


def _summary_lines(result: dict) -> list[str]:
    lines = ["", "## Resumo", "", "| Horizonte | Investimento | Direcao | Risco |",
             "| --- | --- | --- | --- |"]
    for horizon in HORIZONS:
        investment, risk = (result["horizons"][horizon][key] for key in ("investment", "risk"))
        choice = investment.get("class")
        direction = {"Compra": "Comprada", "Compra forte": "Comprada", "Venda": "Vendida",
                     "Venda forte": "Vendida", "Neutro": "Sem posicao"}.get(choice, "-")
        investment_text = choice if investment["status"] == "classificado" else _STATUS_TITLES[investment["status"]]
        risk_text = risk["class"] if risk["status"] == "classificado" else _STATUS_TITLES[risk["status"]]
        lines.append(f"| {HORIZON_TITLES[horizon]} | {investment_text} | {direction} | {risk_text} |")
    return lines


def _risk_scope_lines(result: dict) -> list[str]:
    directions = {row["risk"].get("direction") for row in result["horizons"].values()} - {None}
    if not result.get("risk_scope") or not directions:
        return []
    lines = [RISK_QUALITATIVE_NOTE]
    if "vendida" in directions:
        lines.append(SHORT_POSITION_NOTE)
    return lines


def response_schema(questions, *, for_api=False):
    answers = {}
    for horizon, question in questions.items():
        classes = list(question["criteria"])
        classified = {
            "status": ({"type": "string", "enum": ["classificado"]} if for_api
                       else {"const": "classificado"}),
            "class": {"type": "string", "enum": classes},
            "relatorio": {"type": "string", "minLength": 1},
        }
        insufficient = {"status": ({"type": "string", "enum": ["dados_insuficientes"]} if for_api
                                    else {"const": "dados_insuficientes"}),
                        "reason": {"type": "string", "minLength": 1}}
        # Os status distintos tornam as alternativas disjuntas tambem em anyOf.
        answers[horizon] = {"anyOf" if for_api else "oneOf": [
            {"type": "object", "properties": fields, "required": list(fields),
             "additionalProperties": False} for fields in (classified, insufficient)
        ]}
    return {"type": "object", "properties": {
        "answers": {"type": "object", "properties": answers, "required": list(questions),
                    "additionalProperties": False}}, "required": ["answers"], "additionalProperties": False}


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Resposta textual com chave JSON duplicada.")
        result[key] = value
    return result


def classify_textual_snapshot(snapshot: dict, *, model: str, requester,
                              prompt_builder, parser, format_version: str,
                              structured_output: bool = False) -> dict:
    """requester(prompt) e obrigatorio; testes fornecem somente respostas simuladas."""
    validate_snapshot(snapshot)
    if not isinstance(model, str) or not model.strip():
        raise ValueError("Informe o modelo do relatorio.")
    if not callable(requester):
        raise ValueError("Forneca explicitamente o chamador do relatorio.")
    if not callable(prompt_builder) or not callable(parser):
        raise ValueError("Contrato de prompt e de leitura devem ser chamaveis.")
    investments, questions, stages = {}, {}, []
    for horizon in HORIZONS:
        readiness = check_data_readiness(snapshot["evidence"],
                                        analysis_date=snapshot["analysis_date"], horizon=horizon)
        if readiness["status"] == "pronto":
            questions[horizon] = event_question(build_investment_question(horizon), snapshot.get("event_context"))
        else:
            investments[horizon] = readiness

    def execute(stage_name, state, selected):
        if not selected:
            return {}
        prompt = prompt_builder(state, selected)
        stage = {"stage": stage_name, "prompt": prompt}
        stages.append(stage)
        try:
            if structured_output:
                schema = response_schema(selected, for_api=True)
                stage["response_schema"] = deepcopy(schema)
                reply = requester(prompt, response_schema=schema)
            else:
                reply = requester(prompt)
            text = reply.content if isinstance(reply, LLMResponse) else reply
            stage["response"] = text
            if isinstance(reply, LLMResponse):
                stage["response_metadata"] = deepcopy(reply.metadata)
                reason = reply.metadata.get("done_reason") or reply.metadata.get("finish_reason")
                if reply.metadata.get("done") is False or reason in ("length", "max_tokens"):
                    raise LLMResponseError(
                        f"Geracao incompleta; motivo de encerramento: {reason!r}. Sem reparo ou retry automatico.")
            return parser(text, selected)
        except (LLMError, ValueError) as exc:
            stage["error"] = str(exc)
            return {h: {"status": "erro", "reason": str(exc)} for h in selected}

    investments.update(execute("investment", deepcopy(snapshot), questions))
    directions, risks = prepare_risk_stage(investments)
    questions = {}
    for horizon, direction in directions.items():
        evidence = deepcopy(snapshot["evidence"])
        evidence.update(deepcopy(snapshot["risk_evidence"].get(horizon, {}).get(direction, {})))
        readiness = check_data_readiness(evidence, analysis_date=snapshot["analysis_date"],
                                        horizon=horizon, direction=direction)
        if readiness["status"] == "pronto":
            questions[horizon] = event_question(build_risk_question(horizon, direction), snapshot.get("event_context"))
        else:
            risks[horizon] = {**readiness, "direction": direction}
    risk_state = {"snapshot": deepcopy(snapshot),
                  "risk_directions": {h: directions[h] for h in questions}}
    for horizon, answer in execute("risk", risk_state, questions).items():
        risks[horizon] = {**answer, "direction": directions[horizon]}
    result = {
        "schema_version": SCHEMA_VERSION, "ticker": snapshot["ticker"],
        "analysis_date": snapshot["analysis_date"], "model": model,
        "dataset_id": snapshot_id(snapshot), "rubric_version": RUBRIC_VERSION,
        "instructions_version": INSTRUCTIONS_VERSION,
        "baseline_format_version": format_version,
        "presentation_version": REPORT_PRESENTATION_VERSION,
        "risk_scope": RISK_SCOPE_NOTE,
        "model_state_version": MODEL_STATE_VERSION,
        "horizons": {h: {"investment": investments[h], "risk": risks[h]} for h in HORIZONS},
        "stages": stages,
    }
    if structured_output:
        result["structured_output"] = "on"
    validate_assessment_result(result)
    if "event_context" in snapshot:
        result["event_context"] = deepcopy(snapshot["event_context"])
    return result


def format_report_markdown(result: dict) -> str:
    """Publica metadados em portugues e corpo legivel a partir do resultado interno."""
    validate_assessment_result(result)
    lines = [format_frontmatter(result), "",
             f"{result['ticker']} - {result['analysis_date']}", "",
             f"# Relatorio de investimento - {result['ticker']}", "",
             f"Modelo: {result['model']}", "",
             "> Aviso: projeto experimental. Este relatorio nao constitui recomendacao "
             "de investimento nem orientacao financeira personalizada."]
    lines.extend(_summary_lines(result))
    rows = result["horizons"].values()
    if any(row["investment"].get("class") == "Neutro" for row in rows):
        lines.extend(["", "Neutro: encerrar eventual posicao e ficar sem posicao no horizonte."])
    scope = _risk_scope_lines(result)
    if scope:
        lines.extend(["", *scope])
    events = event_summary_lines(result.get("event_context"))
    if events:
        lines.extend(["", "## Eventos corporativos", ""])
        for line in events:
            lines.append(f"- {' '.join(line.split())}")
    lines.extend(["", "## Analise por horizonte", ""])
    for horizon in HORIZONS:
        lines.extend([f"### {HORIZON_TITLES[horizon]}", "", HORIZON_DESCRIPTIONS[horizon], ""])
        row = result["horizons"][horizon]
        for label in ("investment", "risk"):
            assessment = row[label]
            title = "Investimento" if label == "investment" else "Risco"
            if "direction" in assessment:
                title = f"{title} ({assessment['direction']})"
            if assessment["status"] == "classificado":
                # rationale e aceito somente na apresentacao de resultados antigos.
                narrative = assessment.get("relatorio") or assessment.get("rationale", "")
                content = f"{assessment['class']}. {narrative}"
            else:
                content = _unclassified_text(assessment, row["investment"], label)
            lines.append(f"- **{title}:** {' '.join(content.split())}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
