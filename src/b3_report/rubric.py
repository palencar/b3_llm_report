"""Rubrica experimental e checagens locais; sem coleta ou inferencia."""

from datetime import date
import math

from b3_report.assessment import HORIZONS

RUBRIC_VERSION = "rubrica-comum-v2-risco-qualitativo-experimental"
INSTRUCTIONS_VERSION = "instrucoes-comuns-v4-direcao-experimental"
RISK_QUALITATIVE_NOTE = "Risco qualitativo da posicao hipotetica, sem estimativa numerica de perda."
SHORT_POSITION_NOTE = "A classificacao nao confirma viabilidade nem custos efetivos de aluguel da posicao vendida."
RISK_SCOPE_NOTE = RISK_QUALITATIVE_NOTE + " " + SHORT_POSITION_NOTE
HORIZON_DESCRIPTIONS = {
    "curtissimo": "Mais de zero e ate 3 meses, inclusive.",
    "curto": "Mais de 3 e ate 6 meses, inclusive.",
    "medio": "Mais de 6 e ate 18 meses, inclusive.",
}
INVESTMENT_CRITERIA = {
    "Compra forte": "Direcao comprada com vantagem expressiva: pelo menos tres aspectos independentes favoraveis, incluindo potencial e fundamentos/movimento no horizonte; avaliar fatos contrarios. Nao depende de alta confianca nem exige baixo risco.",
    "Compra": "Direcao comprada favorecida por pelo menos dois aspectos independentes; vantagem moderada ou com condicionantes materiais. Encerrar eventual vendida e abrir comprada.",
    "Neutro": "Evidencias suficientes, sem vantagem clara para comprada ou vendida. Encerrar eventual posicao e ficar sem posicao; risco nao aplicavel.",
    "Venda": "Direcao vendida favorecida por pelo menos dois aspectos independentes; vantagem moderada ou com condicionantes materiais. Encerrar eventual comprada e abrir vendida.",
    "Venda forte": "Direcao vendida com vantagem expressiva: pelo menos tres aspectos independentes favoraveis, incluindo potencial e fundamentos/movimento no horizonte; avaliar fatos contrarios. Nao depende de alta confianca nem exige baixo risco.",
}
RISK_CRITERIA = {
    "Baixo": "Evidencias afirmativas de saude financeira e liquidez adequadas, com exposicao limitada a fatores adversos relevantes para a direcao e o horizonte. Nao basta ausencia de noticias negativas ou baixa volatilidade. Nao significa ausencia de perdas.",
    "Moderado": "Fatores adversos materiais podem causar perdas relevantes, mas as evidencias indicam capacidade de absorcao e saida sem fragilidade severa identificada. Ha condicionantes ou vulnerabilidades relevantes, sem predominio de fatores severos.",
    "Alto": "Ao menos um fator severo sustentado pelas evidencias expoe a posicao a perdas expressivas ou dificuldade importante de saida: fragilidade financeira, liquidez restrita ou sensibilidade acentuada a movimentos adversos e eventos. Considerar a gravidade e a capacidade de absorcao no horizonte, nao apenas contar fatores.",
}
COMMON_INSTRUCTIONS = (
    "Use somente as fontes do snapshot e a data de referencia. Nao use relatorios anteriores "
    "nem complete fatos ausentes. Meses sao de calendario. Preco-alvo sem prazo nao sustenta "
    "sozinho todos os horizontes. Aspectos independentes nao sao repeticoes do mesmo fato "
    "em fontes ou indicadores correlatos. Separe atratividade, risco e confianca. Compra forte "
    "e Venda forte nao definem maior posicao ou alavancagem. As duas classes propoem encerrar "
    "a posicao contraria e abrir a direcao avaliada. Exposicao sem alavancagem, perdas relativas "
    "ao valor inicial exposto, sem presumir stop ou hedge. Para risco, avalie qualitativamente "
    "fatores adversos sustentados pelos dados, nao apenas volatilidade. Nao exija cenario "
    "numerico previamente elaborado nem dados de aluguel; nao invente percentuais de perda. "
    "Falta de dados e checada antes de perguntar ao modelo. "
    "Identifique fonte e periodo dos indicadores materiais. Antes de comparar valores, "
    "verifique indicador, unidade, periodo e base de calculo: trimestre, acumulado, ano "
    "e ultimos doze meses nao sao intercambiaveis. Periodos distintos nao demonstram "
    "contradicao por si so. Nao associe margem de uma fonte/periodo ao lucro ou receita "
    "de outro como se fossem a mesma base. Para calculos derivados, use componentes "
    "compativeis da mesma fonte e periodo e identifique o calculo. Se a base nao estiver "
    "explicitada, registre a limitacao, sem presumir equivalencia. Para o mesmo indicador, "
    "periodo e base comparaveis, siga a fonte primaria declarada no grupo normalizado, "
    "quando existir; explicite divergencia material com o contexto complementar. "
    "Nao faca media nem escolha silenciosamente o valor que favorece a tese. Se nao "
    "houver fonte primaria comparavel ou conciliacao sustentada, nao use a divergencia "
    "como fundamento conclusivo. Incorporacao aos dados nao e precificacao pelo mercado: "
    "incorporacao nao verificada significa apenas desconhecimento da atualizacao dos "
    "dados. Nao afirme que evento esta ou nao incorporado ao preco sem evidencia "
    "explicita de precificacao; a data prevista nao demonstra isso. "
    "Nao apresente volumes de fornecedores diferentes como uma faixa sem verificar "
    "unidade, periodo e metodologia: volume em acoes nao e volume financeiro. "
    "Sem comparabilidade, cite a referencia escolhida e a limitacao, sem combinar valores. "
    "Calendario vazio significa apenas que as fontes nao informaram datas; nao prova "
    "ausencia de eventos ou catalisadores."
)

# Limites operacionais propostos para o primeiro benchmark, em dias corridos.
MAX_AGE_DAYS = {
    "price": 7, "price_trend": 7, "liquidity": 7,
    "valuation": 7, "profitability": 180, "financial_health": 180,
    "growth": 550, "adverse_scenario": 7,
    "borrow_availability": 7, "borrow_cost": 7, "borrow_terms": 7,
}
_INVESTMENT_REQUIREMENTS = {
    "curtissimo": ("price", "price_trend", "liquidity"),
    "curto": ("price", "valuation", "profitability", "financial_health"),
    "medio": ("price", "valuation", "profitability", "financial_health", "growth"),
}
_RISK_REQUIREMENTS = ("price", "liquidity", "financial_health")


def _date(value) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def _has_value(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip()) and value.strip().lower() not in ("n/a", "none", "nan", "n/d")
    if type(value) in (int, float):
        try:
            return math.isfinite(value)
        except OverflowError:
            return False
    if isinstance(value, bool):
        return True
    if isinstance(value, dict):
        return any(_has_value(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_value(item) for item in value)
    return False


def check_data_readiness(evidence: dict, *, analysis_date: str, horizon: str,
                         direction: str | None = None) -> dict:
    """Checa grupos normalizados; pronto nao e uma classe ou garantia de qualidade."""
    reference = _date(analysis_date)
    if reference is None or horizon not in HORIZONS or direction not in (None, "comprada", "vendida"):
        raise ValueError("Data, horizonte ou direcao invalidos para checagem de dados.")
    if not isinstance(evidence, dict):
        raise ValueError("Evidencias devem ser um objeto com grupos normalizados.")
    requirements = _INVESTMENT_REQUIREMENTS[horizon] if direction is None else _RISK_REQUIREMENTS
    reasons = []
    for key in requirements:
        item = evidence.get(key)
        if not isinstance(item, dict) or not _has_value(item.get("value")):
            reasons.append(f"{key}: evidencia ausente ou sem valor valido")
            continue
        source = item.get("source")
        if not isinstance(source, str) or not source.strip():
            reasons.append(f"{key}: fonte ausente")
        observed, available = _date(item.get("as_of")), _date(item.get("available_at"))
        if observed is None or available is None:
            reasons.append(f"{key}: data do dado ou de disponibilidade ausente/invalida")
        elif observed > available or available > reference:
            reasons.append(f"{key}: datas futuras ou cronologia invalida")
        elif (reference - observed).days > MAX_AGE_DAYS[key]:
            reasons.append(f"{key}: dado excede limite de {MAX_AGE_DAYS[key]} dias")
        if item.get("conflict") is not False:
            reasons.append(f"{key}: conflito material ou conciliacao nao informada")
        if key in ("price", "liquidity") and (type(item["value"]) not in (int, float) or item["value"] <= 0):
            reasons.append(f"{key}: valor deve ser um numero positivo")
    if reasons:
        return {"status": "dados_insuficientes", "reason": "; ".join(reasons) + "."}
    return {"status": "pronto"}


def build_investment_question(horizon: str) -> dict:
    if horizon not in HORIZONS:
        raise ValueError("Horizonte invalido para pergunta de investimento.")
    return {"type": "choice", "instructions": (
        f"Classifique investimento no horizonte {horizon}: {HORIZON_DESCRIPTIONS[horizon]} "
        + COMMON_INSTRUCTIONS
    ), "criteria": dict(INVESTMENT_CRITERIA)}


def build_risk_question(horizon: str, direction: str) -> dict:
    if horizon not in HORIZONS or direction not in ("comprada", "vendida"):
        raise ValueError("Horizonte ou direcao invalidos para pergunta de risco.")
    focus = {
        "curtissimo": "Priorize liquidez de saida, movimento de preco e eventos proximos, sem ignorar fragilidade financeira.",
        "curto": "Avalie persistencia dos fatores adversos, resultados, valuation e capacidade financeira durante o horizonte.",
        "medio": "Avalie sustentabilidade financeira, geracao de caixa, endividamento e persistencia de fatores adversos no negocio.",
    }
    return {"type": "choice", "instructions": (
        f"Classifique somente o risco da posicao {direction} no horizonte {horizon}: "
        f"{HORIZON_DESCRIPTIONS[horizon]} " + COMMON_INSTRUCTIONS + " " + focus[horizon] + " "
        + RISK_SCOPE_NOTE + " Considere informacoes opcionais de cenario, aluguel ou noticias "
        "somente quando houver fonte, datas validas ate a referencia e compatibilidade com a "
        "direcao e o horizonte. Informacoes desatualizadas, conflitantes ou de outra direcao "
        "nao sustentam a conclusao. Ausencia dessas informacoes e limitacao, nao insuficiencia "
        "automatica. Nao transforme taxa media em disponibilidade confirmada. "
        "Risco nao e confianca nem atratividade; comprada e vendida nao sao complementos. "
        "A comprada perde com queda do preco; a vendida perde com alta do preco. "
        "Relacione cada fundamento de risco ao mecanismo de perda ou dificuldade de "
        "saida da posicao avaliada, sem inventar eventos ou exigir cenario numerico. "
        "Divida e prejuizos da empresa nao demonstram sozinhos risco Alto para a "
        "vendida; solidez financeira nao demonstra sozinha risco Baixo para ela. "
        "Explique o elo com movimento adverso ou saida usando evidencias disponiveis. "
        "Ausencia de aluguel, noticias ou evidencia de precificacao nao determina "
        "a classe de risco nem impede sua reducao; nao a use como fator adverso "
        "comprovado ou como condicao obrigatoria de revisao. "
        "O contraponto deve limitar a conclusao de risco na direcao avaliada, nao "
        "apenas repetir um argumento favoravel ou contrario ao negocio."
    ), "criteria": dict(RISK_CRITERIA)}
