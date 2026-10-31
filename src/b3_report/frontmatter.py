"""Metadados essenciais em YAML para o frontmatter do relatorio Markdown."""

import json
import re

from b3_report.assessment import HORIZONS, validate_assessment_result

_EVIDENCE_TITLES = {
    "price": "preco", "price_trend": "tendencia de preco", "liquidity": "liquidez",
    "valuation": "avaliacao de valor", "profitability": "rentabilidade",
    "financial_health": "saude financeira", "growth": "crescimento",
    "adverse_scenario": "cenario adverso", "borrow_availability": "disponibilidade de aluguel",
    "borrow_cost": "custo de aluguel", "borrow_terms": "condicoes de aluguel",
}


def readable_reason(reason: str) -> str:
    for key, title in _EVIDENCE_TITLES.items():
        reason = reason.replace(f"{key}: evidencia ausente ou sem valor valido",
                                f"faltam dados validos de {title}")
    return re.sub(r"\b(" + "|".join(_EVIDENCE_TITLES) + r")\b",
                  lambda match: _EVIDENCE_TITLES[match.group()], reason)


def report_frontmatter(result: dict) -> dict:
    """Metadados publicados; narrativas e eventos pertencem ao corpo do relatorio."""
    validate_assessment_result(result)
    summary = {"simbolo": result["ticker"], "data_analise": result["analysis_date"],
               "modelo": result["model"], "horizontes": {}}
    for horizon in HORIZONS:
        row = result["horizons"][horizon]
        values = {}
        investment = row["investment"]
        propagated = (f"Risco nao avaliado: investimento {investment['status']}. "
                      + investment.get("reason", ""))
        for kind, title in (("investment", "investimento"), ("risk", "risco")):
            item = row[kind]
            fields = {"estado": item["status"]}
            for source, target in (("class", "classe"), ("direction", "direcao")):
                if source in item:
                    fields[target] = item[source]
            if ("reason" in item and item["status"] != "nao_aplicavel"
                    and not (kind == "risk" and item["reason"] == propagated)):
                fields["motivo"] = readable_reason(item["reason"])
            values[title] = fields
        summary["horizontes"][horizon] = values
    return summary


def _frontmatter_lines(metadata: dict, indent: int = 0) -> list[str]:
    # O contrato so contem mapas e strings; strings JSON sao escalares YAML validos.
    lines = []
    for key, value in metadata.items():
        prefix = " " * indent + key + ":"
        if isinstance(value, dict):
            lines.append(prefix)
            lines.extend(_frontmatter_lines(value, indent + 2))
        else:
            lines.append(prefix + " " + json.dumps(value, ensure_ascii=False))
    return lines


def format_frontmatter(result: dict) -> str:
    """Serializa apenas metadados publicos; nao inclui narrativa ou dados tecnicos."""
    return "\n".join(["---", *_frontmatter_lines(report_frontmatter(result)), "---"])
