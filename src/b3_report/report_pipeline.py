"""Relatorio unificado sobre snapshot preservado, com retomada auditavel."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import logging
import math
from pathlib import Path
import re
import time

from dotenv import load_dotenv

from b3_core.config import load_config
from b3_report.assessment import validate_assessment_result
from b3_report.snapshot import NORMALIZATION_POLICY, collect_snapshot, load_snapshot, snapshot_id, validate_snapshot
from b3_report.llm import get_investment_analysis, validate_llm_config
from b3_report.reports import write_report_file_atomic
from b3_report.rubric import RUBRIC_VERSION, INSTRUCTIONS_VERSION
from b3_report.report_engine import TEXT_FORMAT_VERSION, format_report_markdown
from b3_report.unified import UNIFIED_FORMAT_VERSION, classify_unified_snapshot
from b3_report.model_state import MODEL_STATE_VERSION
from b3_report.events import AUTO_EVENT_POLICY_VERSION, event_token, load_event_context
from b3_report.token_usage import token_usage_session

VERSION = "assessment-state-v2"
_logger = logging.getLogger(__name__)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode("utf-8")).hexdigest()


def _configuration(config, *, structured_output=False):
    payload = {"version": VERSION, "report_model": config.llm_model,
               "report_endpoint": config.openai_url_base or config.ollama_url_base,
               "rubric": RUBRIC_VERSION, "instructions": INSTRUCTIONS_VERSION,
               "normalization_policy": NORMALIZATION_POLICY,
               "model_state_version": MODEL_STATE_VERSION,
               "event_policy": AUTO_EVENT_POLICY_VERSION,
               "text_format": TEXT_FORMAT_VERSION}
    payload["unified_format"] = UNIFIED_FORMAT_VERSION
    if structured_output:
        payload["structured_output"] = "json-schema-v1"
    return payload


def _identity(config, *, structured_output=False):
    return _digest(_configuration(config, structured_output=structured_output))


def queue_state_path(config, ticker):
    return _state_path(config, ticker, "queue")


def _state_path(config, ticker, scope):
    return Path(config.raw_dir) / "assessments" / f"{ticker}.{scope}.json"


def has_errors(result):
    return any(item["status"] == "erro" for row in result["horizons"].values() for item in row.values())


def _validate_execution(entry, snapshot, model, dataset_id):
    if not isinstance(entry, dict) or entry.get("status") not in ("pending", "done"):
        raise ValueError("Status invalido no estado do relatorio.")
    if set(entry) - {"status", "result", "result_hash", "error"}:
        raise ValueError("Campos externos ao estado autocontido nao sao aceitos.")
    if "result" in entry:
        result = entry["result"]
        validate_assessment_result(result)
        if any(result[key] != value for key, value in (
                ("model", model), ("ticker", snapshot["ticker"]),
                ("analysis_date", snapshot["analysis_date"]), ("dataset_id", dataset_id))):
            raise ValueError("Identidade do resultado diverge do snapshot preservado.")
        if entry.get("result_hash") != _digest(result):
            raise ValueError("Hash do resultado diverge do conteudo.")
        if entry["status"] == "done" and has_errors(result):
            raise ValueError("Estado aponta como concluido um resultado com erro.")
    elif entry["status"] == "done":
        raise ValueError("Estado sem resultado concluido.")


def _read_legacy_state(job, path):
    """Converte somente em memoria, depois de validar o controle e seus resultados."""
    models, modes = job.get("models"), job.get("modes")
    configuration = job["configuration"]
    if (not isinstance(models, dict) or set(models) not in (
            {"unified"}, {"unified", "unified_decision"})
            or not isinstance(modes, dict) or set(modes) != set(models)
            or configuration.get("version") != "assessment-state-v1"
            or configuration.get("decision_model") is not None
            or configuration.get("report_model") != models["unified"]
            or any(model != models["unified"] for model in models.values())):
        raise ValueError(f"Estado antigo nao suportado: {path}")
    for mode, model in models.items():
        _validate_execution(modes[mode], job["snapshot"], model, job["dataset_id"])
    if all(entry["status"] == "done" for entry in modes.values()) and (
            type(job.get("completed_at")) not in (int, float)
            or not math.isfinite(job["completed_at"])):
        raise ValueError("Data de conclusao invalida no estado antigo.")
    job["execution"] = modes["unified"]
    if job["execution"]["status"] == "done" and "completed_at" not in job:
        job["completed_at"] = path.stat().st_mtime
    del job["models"], job["modes"]
    configuration.pop("decision_model", None)
    configuration.pop("decision_endpoint", None)
    configuration["version"] = job["version"] = VERSION
    job["identity"] = _digest(configuration)
    _logger.debug("Estado antigo ticker=%s lido no formato atual, sem regravar arquivo.", job["ticker"])


def load_report_state(config, ticker, *, scope="queue"):
    """Le e valida o estado preservado, sem regravar nem escolher nova configuracao."""
    path = _state_path(config, ticker, scope)
    if path.is_symlink():
        raise ValueError(f"Arquivo de estado nao pode ser link simbolico: {path}")
    if not path.exists():
        return None
    job = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(job, dict) or job.get("version") not in ("assessment-state-v1", VERSION)
            or not isinstance(job.get("identity"), str)
            or not isinstance(job.get("configuration"), dict)
            or job.get("ticker") != ticker or job.get("scope") != scope
            or (scope == "manual" and job.get("trigger_mtime") is not None)
            or (scope == "queue" and (type(job.get("trigger_mtime")) not in (int, float)
                                     or not math.isfinite(job["trigger_mtime"])))):
        raise ValueError(f"Estado do relatorio invalido: {path}")
    if job["identity"] != _digest(job["configuration"]):
        raise ValueError(f"Identidade da configuracao divergente no estado: {path}")
    if "request_id" in job and (not isinstance(job["request_id"], str)
                                or re.fullmatch(r"[0-9a-f]{32}", job["request_id"]) is None):
        raise ValueError(f"Identificador de solicitacao invalido no estado: {path}")
    snapshot = job.get("snapshot")
    validate_snapshot(snapshot)
    if snapshot["ticker"] != ticker or snapshot_id(snapshot) != job.get("dataset_id"):
        raise ValueError("Snapshot diverge do estado; nao recoletar silenciosamente.")
    if job["version"] == "assessment-state-v1":
        _read_legacy_state(job, path)
    configuration = job["configuration"]
    if (configuration.get("version") != VERSION
            or not isinstance(configuration.get("report_model"), str)
            or not configuration["report_model"].strip()
            or {"decision_model", "decision_endpoint"} & set(configuration)
            or {"models", "modes"} & set(job)):
        raise ValueError(f"Configuracao do estado invalida: {path}")
    _validate_execution(job.get("execution"), snapshot, configuration["report_model"], job["dataset_id"])
    if job["execution"]["status"] == "done" and (
            type(job.get("completed_at")) not in (int, float) or not math.isfinite(job["completed_at"])):
        raise ValueError("Data de conclusao invalida no estado do relatorio.")
    expected_transport = "on" if configuration.get("structured_output") == "json-schema-v1" else "off"
    if job.get("structured_output", "off") != expected_transport:
        raise ValueError(f"Transporte diverge da configuracao no estado: {path}")
    return job


def _load_job(config, ticker, structured_output=False, *, scope="queue",
              preserve_completed=False):
    job = load_report_state(config, ticker, scope=scope)
    if job is None:
        return None
    configuration = job["configuration"]
    path = _state_path(config, ticker, scope)
    expected = _configuration(config, structured_output=structured_output)
    if job["identity"] != _digest(expected):
        if job["execution"]["status"] == "pending":
            fields = set(expected) | {"structured_output"}
            changed = [field for field in sorted(fields)
                       if (field in configuration) != (field in expected)
                       or configuration.get(field) != expected.get(field)]
            if set(configuration) - fields:
                changed.append("campos adicionais")
            raise ValueError(f"Configuracao alterada com execucao pendente: {path}. "
                             f"Campos alterados: {', '.join(changed)}. "
                             "Retome a configuracao anterior ou reinicie manualmente esse estado com o watcher parado.")
        # Na elegibilidade, configuracao nova nao equivale a um novo alerta.
        if preserve_completed:
            return job
        _logger.info("Configuracao alterada ticker=%s; estado concluido sera substituido, sem historico.", ticker)
        return None
    return job


def should_run_report(config, ticker, trigger_mtime, structured_output=False, *, request_id=None):
    job = _load_job(config, ticker,
                    structured_output=structured_output, preserve_completed=True)
    if job is None:
        return True, "relatorio unificado ausente"
    if job["execution"]["status"] == "pending":
        return True, "retomar relatorio pendente no snapshot preservado"
    if request_id is not None:
        if job.get("request_id") == request_id:
            return False, "solicitacao manual ja concluida"
        return True, "atualizacao obrigatoria solicitada"
    context = load_event_context(config, ticker)
    if context is not None and event_token(context) != job.get("event_state"):
        return True, "calendario ou fase de evento alterado"
    if trigger_mtime <= job["trigger_mtime"]:
        return False, "relatorio unificado ja concluido"
    age = (time.time() - job["completed_at"]) / 3600
    if age < config.report_min_age_hours:
        return False, "relatorio unificado muito recente"
    return True, "novo alerta com relatorio unificado antigo"


def _validate_identity(result, snapshot, model):
    validate_assessment_result(result)
    if any(result[key] != value for key, value in (
        ("model", model), ("ticker", snapshot["ticker"]), ("analysis_date", snapshot["analysis_date"]),
        ("dataset_id", snapshot_id(snapshot)), ("rubric_version", RUBRIC_VERSION),
        ("instructions_version", INSTRUCTIONS_VERSION))):
        raise ValueError("Identidade do resultado diverge do snapshot/rubrica compartilhados.")


@token_usage_session()
def run_report(symbol, *, snapshot_path=None, config=None, trigger_mtime=None,
                reports_dir="reports", textual_requester=None,
                structured_output=False, request_id=None):
    if config is None:
        load_dotenv()
        config = load_config()
    validate_llm_config(config.llm_model, config.openai_url_base, config.ollama_url_base)
    symbol = symbol.upper()
    if re.fullmatch(r"[A-Z0-9]{3,6}", symbol) is None:
        raise ValueError("Ticker invalido para o relatorio unificado.")
    if trigger_mtime is not None and snapshot_path is not None:
        raise ValueError("Fila unificada nao recebe snapshot externo junto com alerta.")
    if trigger_mtime is not None and (type(trigger_mtime) not in (int, float) or not math.isfinite(trigger_mtime)):
        raise ValueError("Data do alerta invalida para o relatorio unificado.")
    scope = "queue" if trigger_mtime is not None else "manual"
    if request_id is not None and (scope != "queue" or not isinstance(request_id, str)
                                   or re.fullmatch(r"[0-9a-f]{32}", request_id) is None):
        raise ValueError("Solicitacao obrigatoria exige fila e identificador valido.")
    current = _load_job(config, symbol,
                        structured_output=structured_output, scope=scope)
    pending = current and current["execution"]["status"] == "pending"
    job = current if scope == "queue" or pending else None
    if job and scope == "manual" and snapshot_path:
        if snapshot_id(load_snapshot(snapshot_path)) != job["dataset_id"]:
            raise ValueError("Snapshot externo diverge da execucao manual pendente; preserve ou reinicie o estado manual.")
    state_path = _state_path(config, symbol, scope).resolve()
    if job and job["execution"]["status"] == "done":
        context = load_event_context(config, symbol)
        if ((request_id is not None and job.get("request_id") != request_id)
                or trigger_mtime > job["trigger_mtime"]
                or (context is not None and event_token(context) != job.get("event_state"))):
            job = None
    if job:
        snapshot = deepcopy(job["snapshot"])
    else:
        if snapshot_path:
            snapshot = load_snapshot(snapshot_path)
            if snapshot["ticker"] != symbol:
                raise ValueError("Ticker solicitado diverge do snapshot preservado.")
        else:
            snapshot = collect_snapshot(symbol, config, datetime.now(timezone.utc).date().isoformat())
        validate_snapshot(snapshot)
        if snapshot["ticker"] != symbol:
            raise ValueError("Ticker coletado diverge do alerta.")
        job = {"version": VERSION,
               "identity": _identity(config, structured_output=structured_output), "ticker": symbol,
               "configuration": _configuration(config,
                                                 structured_output=structured_output),
               "scope": scope,
               "event_state": event_token(snapshot.get("event_context")),
               "trigger_mtime": trigger_mtime, "snapshot": snapshot, "dataset_id": snapshot_id(snapshot),
               "execution": {"status": "pending"}}
        if structured_output:
            job["structured_output"] = "on"
        write_report_file_atomic(state_path, json.dumps(job))
    if request_id is not None and job.get("request_id") != request_id:
        # Uma pendencia existente e retomada, sem descartar o snapshot preservado.
        job["request_id"] = request_id
        write_report_file_atomic(state_path, json.dumps(job))
    _logger.info("Relatorio unificado ticker=%s dataset_id=%s data=%s", symbol, job["dataset_id"],
                 snapshot["analysis_date"])
    results, attempted, failed = {}, [], []
    mode = "unified"
    model = config.llm_model
    entry = job["execution"]
    if entry["status"] == "done":
        results[mode] = deepcopy(entry["result"])
    else:
        attempted.append(mode)
        _logger.info("Processando ticker=%s modo=%s modelo=%s snapshot compartilhado", symbol, mode, model)
        try:
            result = entry.get("result")
            if result is None or has_errors(result):
                requester = textual_requester
                if requester is None:
                    def requester(prompt, *, response_schema=None):
                        return get_investment_analysis(prompt, model=model, api_key=config.llm_api_key,
                                                       openai_url_base=config.openai_url_base,
                                                       ollama_url_base=config.ollama_url_base,
                                                       response_schema=response_schema, with_metadata=True)
                result = classify_unified_snapshot(deepcopy(snapshot), model=model, requester=requester,
                                                   structured_output=structured_output)
            else:
                _logger.info("Retomando publicacao ticker=%s com resultado preservado, sem nova chamada ao modelo.", symbol)
            _validate_identity(result, snapshot, model)
            results[mode] = result
            entry.update(result=deepcopy(result), result_hash=_digest(result))
            if has_errors(result):
                raise RuntimeError(f"Modo {mode} retornou erro; snapshot preservado para retomada.")
            entry.pop("error", None)
            # Preserva o resultado antes de publicar; arquivo e estado nao sao uma unica transacao.
            write_report_file_atomic(state_path, json.dumps(job))
            text = format_report_markdown(result)
            write_report_file_atomic(Path(reports_dir) / f"{symbol}.md", text)
            (Path(reports_dir) / f"{symbol}.json").unlink(missing_ok=True)
            _logger.info("Relatorio publicado com frontmatter: %s", Path(reports_dir) / f"{symbol}.md")
            entry.update(status="done")
            _logger.info("Concluido ticker=%s modo=%s dataset_id=%s", symbol, mode, job["dataset_id"])
        except Exception as exc:
            failed.append(mode)
            entry["error"] = str(exc)
            _logger.exception("Falha ticker=%s modo=%s; mesmo snapshot preservado.", symbol, mode)
        if entry["status"] == "done":
            job["completed_at"] = time.time()
        write_report_file_atomic(state_path, json.dumps(job))
    return {"results": results, "attempted": attempted, "failed_modes": failed,
            "snapshot_path": str(state_path), "manifest_path": str(state_path), "dataset_id": job["dataset_id"]}
