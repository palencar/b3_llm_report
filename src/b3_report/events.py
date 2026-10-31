"""Calendario local auditavel; avisos de evento nao sao classes financeiras."""

from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo
from b3_report.reports import write_report_file_atomic

EVENT_POLICY_VERSION = "eventos-v2-experimental-7d"
AUTO_EVENT_POLICY_VERSION = "eventos-yahoo-v2-experimental-7d"
_LEGACY_POLICIES = ("eventos-v1-experimental-7d", "eventos-yahoo-v1-experimental-7d")
_PENDING_DAYS = 7
_OLD_PHASE = "evento_antigo_verificacao_pendente"


def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError("Evento: horario deve ser ISO 8601 com fuso.")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Evento: horario deve incluir fuso.")
    return parsed


def _validate_event(event):
    required = {"id", "ticker", "type", "event_date", "event_time", "timezone", "source",
                "available_at", "checked_at", "status", "incorporation", "incorporated_at"}
    automatic = isinstance(event, dict) and event.get("origin") == "yahoo-info"
    if automatic:
        required |= {"origin", "certainty", "provider_start_at", "provider_end_at", "provider_point_at", "publication_at"}
    if not isinstance(event, dict) or set(event) != required:
        raise ValueError("Evento: campos diferentes do contrato corporate-events-v1.")
    for field in ("id", "type", "source"):
        if not isinstance(event[field], str) or not event[field].strip():
            raise ValueError(f"Evento: {field} obrigatorio.")
    if not isinstance(event["ticker"], str) or re.fullmatch(r"[A-Z0-9]{3,6}", event["ticker"]) is None:
        raise ValueError("Evento: ticker invalido.")
    if date.fromisoformat(event["event_date"]).isoformat() != event["event_date"]:
        raise ValueError("Evento: data deve ser YYYY-MM-DD.")
    ZoneInfo(event["timezone"])
    if event["event_time"] is not None and (not isinstance(event["event_time"], str)
            or re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", event["event_time"]) is None):
        raise ValueError("Evento: use HH:MM ou null para horario desconhecido.")
    available, checked = (_timestamp(event[k]) for k in ("available_at", "checked_at"))
    if available > checked:
        raise ValueError("Evento: disponibilidade posterior a consulta.")
    if event["status"] not in ("previsto", "divulgado", "cancelado"):
        raise ValueError("Evento: status invalido.")
    if event["status"] == "divulgado" and checked.astimezone(ZoneInfo(event["timezone"])).date() < date.fromisoformat(event["event_date"]):
        raise ValueError("Evento: divulgacao confirmada antes da data prevista.")
    if event["incorporation"] not in ("dados_anteriores", "atualizados", "nao_verificado"):
        raise ValueError("Evento: incorporacao invalida.")
    if event["incorporation"] == "atualizados":
        incorporated = _timestamp(event["incorporated_at"])
        if event["status"] != "divulgado" or not available <= incorporated <= checked:
            raise ValueError("Evento: incorporacao exige divulgacao e cronologia valida.")
        if incorporated.astimezone(ZoneInfo(event["timezone"])).date() < date.fromisoformat(event["event_date"]):
            raise ValueError("Evento: incorporacao anterior ao evento.")
        if event["event_time"] is not None:
            scheduled = datetime.fromisoformat(event["event_date"] + "T" + event["event_time"]).replace(tzinfo=ZoneInfo(event["timezone"]))
            if incorporated < scheduled:
                raise ValueError("Evento: incorporacao anterior ao horario do evento.")
    elif event["incorporated_at"] is not None:
        raise ValueError("Evento: incorporated_at exige dados atualizados.")
    if automatic:
        start, end = _timestamp(event["provider_start_at"]), _timestamp(event["provider_end_at"])
        if event["provider_point_at"] is not None:
            _timestamp(event["provider_point_at"])
        if (start > end or event["publication_at"] is not None or event["status"] != "previsto"
                or event["incorporation"] != "nao_verificado"
                or event["certainty"] not in ("estimativa", "nao_marcada_como_estimativa", "desconhecida")
                or not event["id"].startswith("yahoo-info-")):
            raise ValueError("Evento Yahoo: intervalo ou certeza invalidos; nao presumir confirmacao.")
        local = start.astimezone(ZoneInfo(event["timezone"]))
        if event["event_date"] != local.date().isoformat():
            raise ValueError("Evento Yahoo: data diverge do timestamp original.")
        expected_time = local.strftime("%H:%M") if start == end else None
        if event["event_time"] != expected_time:
            raise ValueError("Evento Yahoo: horario pontual nao pode representar intervalo.")


def _phase(event, cutoff, *, policy_version=EVENT_POLICY_VERSION):
    if policy_version not in _LEGACY_POLICIES:
        resolved = (event["status"] == "cancelado"
                    or (event["status"] == "divulgado" and event["incorporation"] == "atualizados"))
        local_cutoff = cutoff.astimezone(ZoneInfo(event["timezone"]))
        last_date = date.fromisoformat(event["event_date"])
        if event.get("origin") == "yahoo-info":
            timestamps = [_timestamp(event["provider_end_at"])]
            if event["provider_point_at"] is not None:
                timestamps.append(_timestamp(event["provider_point_at"]))
            # Uma data divergente recente/futura nao deve ser ocultada como antiga.
            last_date = max(timestamps).astimezone(local_cutoff.tzinfo).date()
        if not resolved and (local_cutoff.date() - last_date).days > _PENDING_DAYS:
            return _OLD_PHASE
    if event.get("origin") == "yahoo-info":
        start, end = _timestamp(event["provider_start_at"]), _timestamp(event["provider_end_at"])
        if event["provider_point_at"] is not None and not start <= _timestamp(event["provider_point_at"]) <= end:
            return "datas_divergentes_verificacao_pendente"
        if cutoff >= end:
            return "data_prevista_atingida_confirmacao_pendente"
        if start <= cutoff < end:
            return "intervalo_previsto_em_curso"
        local_cutoff = cutoff.astimezone(ZoneInfo(event["timezone"]))
        days = (start.astimezone(local_cutoff.tzinfo).date() - local_cutoff.date()).days
        return "evento_proximo" if days <= 7 else "fora_janela_proximidade"
    local = cutoff.astimezone(ZoneInfo(event["timezone"]))
    days = (date.fromisoformat(event["event_date"]) - local.date()).days
    if event["status"] == "cancelado":
        return "cancelado"
    if event["status"] == "divulgado":
        return "incorporado" if event["incorporation"] == "atualizados" else "divulgado_atualizacao_pendente"
    if days < 0:
        return "data_prevista_atingida_confirmacao_pendente"
    if days == 0:
        if event["event_time"] is None:
            return "evento_hoje_horario_desconhecido"
        scheduled = datetime.fromisoformat(event["event_date"] + "T" + event["event_time"]).replace(tzinfo=local.tzinfo)
        if scheduled <= local:
            return "data_prevista_atingida_confirmacao_pendente"
    return "evento_proximo" if days <= 7 else "fora_janela_proximidade"


def _yahoo_observation_path(config, ticker):
    raw_dir = getattr(config, "raw_dir", "")
    return Path(raw_dir) / "event-observations" / f"{ticker}.json" if raw_dir else None


def _yahoo_events(observation, ticker, cutoff):
    if observation.get("ticker") != ticker:
        raise ValueError("Observacao Yahoo diverge do ticker.")
    observed = _timestamp(observation["observed_at"])
    if observed > cutoff:
        return []
    metadata = observation["metadata"]
    dates = metadata.get("timestamps_utc", {})
    start = dates.get("earningsTimestampStart")
    end = dates.get("earningsTimestampEnd")
    # Intervalo incompleto nao e convertido silenciosamente em data pontual.
    if start is None and end is None:
        start = end = dates.get("earningsTimestamp")
    if start is None or end is None:
        return []
    first, last = _timestamp(start), _timestamp(end)
    if first > last:
        raise ValueError("Yahoo forneceu intervalo de resultados invertido.")
    name = metadata.get("raw_fields", {}).get("exchangeTimezoneName")
    zone = ZoneInfo(name) if name else timezone.utc
    local = first.astimezone(zone)
    event = {"id": "yahoo-info-resultados", "ticker": ticker, "type": "resultados",
             "event_date": local.date().isoformat(), "event_time": local.strftime("%H:%M") if first == last else None,
             "timezone": name or "UTC", "source": metadata["source"],
             "available_at": observation["observed_at"], "checked_at": observation["observed_at"],
             "status": "previsto", "incorporation": "nao_verificado", "incorporated_at": None,
             "origin": "yahoo-info", "certainty": metadata["certainty"],
             "provider_start_at": first.isoformat(), "provider_end_at": last.isoformat(),
             "provider_point_at": dates.get("earningsTimestamp"), "publication_at": None}
    _validate_event(event)
    return [{**event, "phase": _phase(event, cutoff)}]


def load_event_context(config, ticker, *, as_of=None, yfinance_data=None):
    path = getattr(config, "corporate_events_file", "")
    observation_path = _yahoo_observation_path(config, ticker)
    if (not path and (yfinance_data is None or "Event Metadata" not in yfinance_data)
            and (observation_path is None or not observation_path.exists())):
        return None
    cutoff = datetime.now(timezone.utc) if as_of is None else as_of
    if cutoff.tzinfo is None:
        raise ValueError("Calendario exige instante de referencia com fuso.")
    payload = json.loads(Path(path).read_text(encoding="utf-8")) if path else {"version": "corporate-events-v1", "events": []}
    if (not isinstance(payload, dict) or set(payload) != {"version", "events"}
            or payload["version"] != "corporate-events-v1" or not isinstance(payload["events"], list)):
        raise ValueError("Calendario invalido: use corporate-events-v1 e lista events.")
    events, seen = [], set()
    for event in payload["events"]:
        _validate_event(event)
        identity = event["ticker"], event["id"]
        if identity in seen:
            raise ValueError("Evento duplicado no calendario.")
        seen.add(identity)
        if event["ticker"] == ticker and _timestamp(event["available_at"]) <= cutoff and _timestamp(event["checked_at"]) <= cutoff:
            events.append({**event, "phase": _phase(event, cutoff)})
    observation = None
    if yfinance_data is not None and "Event Metadata" in yfinance_data:
        observation = {"ticker": ticker, "metadata": yfinance_data["Event Metadata"],
                       "observed_at": yfinance_data["Source Metadata"]["Fetched At"]}
    elif observation_path is not None and observation_path.exists():
        observation = json.loads(observation_path.read_text(encoding="utf-8"))
    if observation is not None:
        events.extend(_yahoo_events(observation, ticker, cutoff))
        if yfinance_data is not None and observation_path is not None:
            write_report_file_atomic(observation_path, json.dumps(observation, ensure_ascii=False, allow_nan=False))
    if not path and observation is None:
        return None
    events.sort(key=lambda e: (e["event_date"], e["id"]))
    return {"policy_version": AUTO_EVENT_POLICY_VERSION if observation is not None else EVENT_POLICY_VERSION,
            "as_of": cutoff.isoformat(),
            "coverage": ("Yahoo observado na coleta e calendario manual opcional; nao exaustivo; "
                         "disponibilidade e observacao, nao publicacao; fontes nao conciliadas; "
                         "ausencia nao comprova ausencia de eventos"),
            "proximity_days": 7, "pending_days": _PENDING_DAYS, "events": events}


def validate_event_context(context, ticker, analysis_date):
    legacy = isinstance(context, dict) and context.get("policy_version") in _LEGACY_POLICIES
    fields = {"policy_version", "as_of", "coverage", "proximity_days", "events"}
    if not legacy:
        fields.add("pending_days")
    if (not isinstance(context, dict) or set(context) != fields
            or context["policy_version"] not in (EVENT_POLICY_VERSION, AUTO_EVENT_POLICY_VERSION, *_LEGACY_POLICIES)
            or context["proximity_days"] != 7
            or (not legacy and context["pending_days"] != _PENDING_DAYS)
            or not isinstance(context["coverage"], str) or not isinstance(context["events"], list)):
        raise ValueError("Contexto de eventos invalido.")
    cutoff = _timestamp(context["as_of"])
    if cutoff.astimezone(timezone.utc).date().isoformat() != analysis_date:
        raise ValueError("Contexto de eventos diverge da data UTC do snapshot.")
    seen = set()
    for item in context["events"]:
        event = {k: v for k, v in item.items() if k != "phase"}
        _validate_event(event)
        if (event["ticker"] != ticker or event["id"] in seen or _timestamp(event["checked_at"]) > cutoff
                or item.get("phase") != _phase(event, cutoff, policy_version=context["policy_version"])):
            raise ValueError("Evento diverge do ticker, conhecimento disponivel ou fase.")
        seen.add(event["id"])


def event_token(context):
    if context is None or not context["events"]:
        return None
    # O relogio de consulta nao deve gerar nova execucao a cada polling.
    content = {k: v for k, v in context.items() if k != "as_of"}
    content["events"] = [
        {k: v for k, v in event.items() if k not in ("available_at", "checked_at")}
        if event.get("origin") == "yahoo-info" else event
        for event in context["events"]
    ]
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def active_event(context):
    return context is not None and any(e["phase"] not in ("cancelado", "incorporado", "fora_janela_proximidade", _OLD_PHASE)
                                       for e in context["events"])


def event_lines(context):
    if context is None:
        return []
    lines = ["Eventos corporativos: " + context["coverage"], "Referencia dos eventos: " + context["as_of"]]
    for event in context["events"]:
        lines.append(f"Evento {event['type']} em {event['event_date']} "
                     f"{event['event_time'] or '(horario desconhecido)'} {event['timezone']}: "
                     f"{event['phase']}; incorporacao={event['incorporation']}; fonte={event['source']}; "
                     f"consultado={event['checked_at']}; disponivel={event['available_at']}.")
        if event.get("origin") == "yahoo-info":
            lines.append(f"Yahoo: certeza={event['certainty']}; intervalo UTC "
                         f"{event['provider_start_at']} ate {event['provider_end_at']}; "
                         f"timestamp pontual={event['provider_point_at']}; "
                         "horario do fornecedor, nao confirmado pelo RI; publicacao original desconhecida.")
    if any(event["phase"] == _OLD_PHASE for event in context["events"]):
        lines.append("Data antiga: fora da janela de pendencia recente de sete dias corridos; "
                     "verificacao continua pendente. Nao e alerta de proximidade nem confirmacao "
                     "de divulgacao ou incorporacao aos dados.")
    if active_event(context):
        lines.append("Atencao: evento proximo ou atualizacao pendente; possivel descontinuidade de preco. "
                     "O calendario nao determina direcao, magnitude de perda ou classe de risco.")
    return lines


def event_summary_lines(context):
    """Resumo de apresentacao; nao modifica o contexto nem a politica de eventos."""
    if context is None:
        return []
    phases = {
        "evento_proximo": "evento proximo",
        "fora_janela_proximidade": "fora da janela de proximidade",
        "data_prevista_atingida_confirmacao_pendente": "data prevista atingida; divulgacao e incorporacao nao confirmadas",
        "intervalo_previsto_em_curso": "intervalo previsto em curso",
        "datas_divergentes_verificacao_pendente": "datas divergentes; verificacao pendente",
        "evento_hoje_horario_desconhecido": "previsto para hoje; horario desconhecido",
        "divulgado_atualizacao_pendente": "divulgado; atualizacao dos dados pendente",
        "incorporado": "divulgado e incorporado aos dados",
        "cancelado": "cancelado",
        _OLD_PHASE: "data antiga; verificacao pendente, sem alerta de proximidade",
    }
    lines = []
    for event in context["events"]:
        when = date.fromisoformat(event["event_date"]).strftime("%d/%m/%Y")
        when += " " + (event["event_time"] or "horario nao informado") + " " + event["timezone"]
        source = event["source"]
        if event.get("origin") == "yahoo-info":
            source = "Yahoo Finance"
            start, end = event["provider_start_at"], event["provider_end_at"]
            if start != end:
                when = f"intervalo {start} a {end}"
            if event["phase"] == "datas_divergentes_verificacao_pendente":
                when += f"; data pontual divergente: {event['provider_point_at']}"
            if event["certainty"] == "estimativa":
                when += " (estimativa)"
        phase = phases.get(event["phase"], event["phase"].replace("_", " "))
        lines.append(f"{event['type'].replace('_', ' ').capitalize()}: {when}; {phase}. Fonte: {source}.")
    if not lines:
        lines.append("Nenhuma data de evento informada pelas fontes consultadas.")
    if active_event(context):
        lines.append("Atencao: possivel descontinuidade de preco; a data nao determina direcao nem classe de risco.")
    if any(event.get("origin") == "yahoo-info" for event in context["events"]):
        lines.append("Datas e horarios do Yahoo nao confirmados pelo RI.")
    lines.append("Calendario parcial: ausencia de registro nao significa ausencia de eventos.")
    return lines
