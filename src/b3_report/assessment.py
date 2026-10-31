"""Contrato comum de investimento e risco; sem coleta ou chamadas a modelos."""

from datetime import date
import re

SCHEMA_VERSION = "assessment-v3"
HORIZONS = ("curtissimo", "curto", "medio")
INVESTMENT_CLASSES = ("Compra forte", "Compra", "Neutro", "Venda", "Venda forte")
RISK_CLASSES = ("Baixo", "Moderado", "Alto")
STATUSES = ("classificado", "dados_insuficientes", "erro")
_DIRECTIONS = {"Compra forte": "comprada", "Compra": "comprada",
               "Venda": "vendida", "Venda forte": "vendida"}


class AssessmentValidationError(ValueError):
    """Resultado estruturado fora do contrato comum."""


def _require(condition: bool, context: str, message: str) -> None:
    if not condition:
        raise AssessmentValidationError(f"{context}: {message}")


def _nonempty_text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_classification_result(value, classes: tuple[str, ...], context: str,
                                   *, allow_not_applicable: bool = False,
                                   allow_legacy_metadata: bool = False) -> None:
    """Valida uma classificacao isolada com as opcoes explicitas da pergunta."""
    _require(isinstance(value, dict), context, "resultado deve ser um objeto.")
    statuses = STATUSES + ("nao_aplicavel",) if allow_not_applicable else STATUSES
    _require(value.get("status") in statuses, context, "status invalido.")
    if not allow_legacy_metadata:
        _require(not {"probabilities", "confidence", "probability_source"} & set(value),
                 context, "metadados de probabilidade ou confianca nao sao aceitos.")
    if value["status"] != "classificado":
        _require(_nonempty_text(value.get("reason")), context, "motivo obrigatorio.")
        _require(not any(key in value for key in ("class", "probabilities", "confidence")),
                 context, "resultado nao classificado nao pode conter classe ou metadados removidos.")
        return
    _require(value.get("class") in classes, context, "classe invalida.")


def prepare_risk_stage(investments: dict) -> tuple[dict[str, str], dict[str, dict]]:
    """Separa direcoes a avaliar dos riscos resolvidos sem consultar o modelo."""
    _require(isinstance(investments, dict) and set(investments) == set(HORIZONS),
             "investment", "informe exatamente curtissimo, curto e medio.")
    directions, resolved = {}, {}
    for horizon in HORIZONS:
        investment = investments[horizon]
        validate_classification_result(investment, INVESTMENT_CLASSES, f"{horizon}.investment")
        if investment["status"] != "classificado":
            resolved[horizon] = {
                "status": investment["status"],
                "reason": f"Risco nao avaliado: investimento {investment['status']}. {investment['reason']}",
            }
        elif investment["class"] == "Neutro":
            resolved[horizon] = {
                "status": "nao_aplicavel",
                "reason": "Neutro: encerrar eventual posicao e ficar sem posicao no horizonte.",
            }
        else:
            directions[horizon] = _DIRECTIONS[investment["class"]]
    return directions, resolved


def validate_assessment_result(result: dict) -> None:
    """Valida estrutura e coerencia, sem julgar qualidade financeira ou alterar dados."""
    _require(isinstance(result, dict), "resultado", "deve ser um objeto.")
    _require(result.get("schema_version") in (SCHEMA_VERSION, "assessment-v2"),
             "resultado", "versao de contrato invalida.")
    legacy = result["schema_version"] == "assessment-v2"
    if not legacy:
        _require("probability_source" not in result, "resultado", "origem de probabilidades nao e aceita.")
    for field in ("ticker", "model", "dataset_id", "rubric_version", "instructions_version"):
        _require(_nonempty_text(result.get(field)), field, "texto obrigatorio.")
    _require(re.fullmatch(r"[A-Z0-9]{3,6}", result["ticker"]) is not None,
             "ticker", "identificacao invalida.")
    analysis_date = result.get("analysis_date")
    _require(isinstance(analysis_date, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", analysis_date) is not None,
             "analysis_date", "use YYYY-MM-DD.")
    try:
        date.fromisoformat(analysis_date)
    except ValueError as exc:
        raise AssessmentValidationError("analysis_date: data inexistente.") from exc
    horizons = result.get("horizons")
    _require(isinstance(horizons, dict) and set(horizons) == set(HORIZONS),
             "horizons", "informe exatamente curtissimo, curto e medio.")
    for horizon in HORIZONS:
        row = horizons[horizon]
        _require(isinstance(row, dict) and set(row) == {"investment", "risk"},
                 horizon, "informe investimento e risco separadamente.")
        investment, risk = row["investment"], row["risk"]
        validate_classification_result(investment, INVESTMENT_CLASSES, f"{horizon}.investment",
                                       allow_legacy_metadata=legacy)
        validate_classification_result(risk, RISK_CLASSES, f"{horizon}.risk", allow_not_applicable=True,
                                       allow_legacy_metadata=legacy)
        direction = risk.get("direction")
        if "direction" in risk:
            _require(direction in ("comprada", "vendida"), f"{horizon}.risk", "direcao invalida.")
        if investment["status"] != "classificado":
            _require(risk["status"] == investment["status"] and "direction" not in risk,
                     horizon, "risco nao pode presumir direcao sem investimento classificado.")
            continue
        if investment["class"] == "Neutro":
            _require(risk["status"] == "nao_aplicavel" and "direction" not in risk,
                     horizon, "Neutro exige risco nao_aplicavel, sem direcao.")
            continue
        _require(risk["status"] != "nao_aplicavel", horizon,
                 "risco de posicao comprada ou vendida nao pode ser nao_aplicavel.")
        _require(direction in ("comprada", "vendida"), f"{horizon}.risk", "direcao obrigatoria.")
        expected = _DIRECTIONS.get(investment.get("class"))
        if expected is not None and direction is not None:
            _require(direction == expected, horizon, "direcao do risco diverge da classe de investimento.")
