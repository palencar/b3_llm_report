from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from b3_report import aligned_pipeline as pipeline
from b3_report.assessment import HORIZONS
from b3_report.decision_snapshot import SNAPSHOT_VERSION, load_decision_snapshot, snapshot_id
from b3_report.rubric import MAX_AGE_DAYS


@pytest.fixture
def snapshot():
    groups = {key: {"value": 1.0, "source": "simulada", "as_of": "2026-10-13",
                    "available_at": "2026-10-13", "conflict": False}
              for key in MAX_AGE_DAYS if not key.startswith("borrow_") and key != "adverse_scenario"}
    return {"snapshot_version": SNAPSHOT_VERSION, "ticker": "WEGE3", "analysis_date": "2026-10-13",
            "evidence": groups, "risk_evidence": {},
            "source_data": {"yfinance": {}, "fundamentus": "", "cvm": []}}


@pytest.fixture
def config(tmp_path, monkeypatch, snapshot):
    monkeypatch.setattr(pipeline, "collect_decision_snapshot", Mock(return_value=deepcopy(snapshot)))
    monkeypatch.setattr(pipeline, "get_investment_analysis", Mock(side_effect=AssertionError("Sem chamada real.")))
    return SimpleNamespace(raw_dir=str(tmp_path / "raw"), llm_model="chat-simulado", llm_api_key="",
                           ollama_url_base="http://simulado", openai_url_base="", report_min_age_hours=0)


def sender(prompt, **kwargs):
    payload = json.loads(prompt.split("\n", 1)[1])
    choice = "Alto" if "risk_directions" in payload["state"] else "Compra"
    return json.dumps({"answers": {h: {"status": "classificado", "class": choice,
        "relatorio": "Fundamento simulado."} for h, q in payload["questions"].items()}})


def run(config, tmp_path, **kwargs):
    return pipeline.run_aligned("WEGE3", config=config, reports_dir=str(tmp_path / "reports"),
                                textual_requester=kwargs.pop("textual_requester", sender), **kwargs)


def legacy_state(state, config):
    state = deepcopy(state)
    state["version"] = state["configuration"]["version"] = "assessment-state-v1"
    state["configuration"]["decision_model"] = None
    state["configuration"]["decision_endpoint"] = config.ollama_url_base
    state["identity"] = pipeline._digest(state["configuration"])
    state["models"] = {"unified": config.llm_model}
    state["modes"] = {"unified": state.pop("execution")}
    return state


def test_unificado_preserva_snapshot_e_publica_frontmatter(config, tmp_path, snapshot):
    calls = []
    def requester(prompt):
        calls.append(prompt)
        return sender(prompt)
    result = run(config, tmp_path, trigger_mtime=100, textual_requester=requester)
    assert not result["failed_modes"]
    assert len(calls) == 2
    assert result["dataset_id"] == snapshot_id(snapshot)
    pipeline.collect_decision_snapshot.assert_called_once()
    assert set(result["results"]) == {"unified"}
    report = (tmp_path / "reports" / "WEGE3.md").read_text()
    assert report.startswith('---\nsimbolo: "WEGE3"\n')
    assert not (tmp_path / "reports" / "WEGE3.json").exists()
    state = json.loads(Path(result["manifest_path"]).read_text())
    assert state["snapshot"] == snapshot
    assert state["execution"]["result"] == result["results"]["unified"]
    assert "models" not in state and "modes" not in state


def test_falha_preserva_publicacao_e_retoma_sem_recoleta(config, tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir()
    path = reports / "WEGE3.md"
    path.write_text("Anterior")
    first = run(config, tmp_path, trigger_mtime=100, textual_requester=lambda p: "{}")
    assert first["failed_modes"] == ["unified"]
    assert path.read_text() == "Anterior"
    monkeypatch.setattr(pipeline, "collect_decision_snapshot", Mock(side_effect=AssertionError("Sem recoleta.")))
    second = run(config, tmp_path, trigger_mtime=101)
    assert not second["failed_modes"]
    assert second["dataset_id"] == first["dataset_id"]
    state = json.loads(Path(second["manifest_path"]).read_text())
    assert state["trigger_mtime"] == 100


@pytest.mark.parametrize("derived_status", ["pending", "done"])
def test_estado_antigo_lido_sem_repetir_chat(config, tmp_path, derived_status):
    first = run(config, tmp_path, trigger_mtime=100)
    path = Path(first["manifest_path"])
    state = legacy_state(json.loads(path.read_text()), config)
    state["models"]["unified_decision"] = config.llm_model
    state["modes"]["unified_decision"] = (
        deepcopy(state["modes"]["unified"]) if derived_status == "done" else {"status": "pending"})
    if derived_status == "pending":
        del state["completed_at"]
    path.write_text(json.dumps(state))
    before = path.read_bytes()
    assert not pipeline.should_run_aligned(config, "WEGE3", 100)[0]
    assert path.read_bytes() == before
    forbidden = Mock(side_effect=AssertionError("Nao repetir chat."))
    second = run(config, tmp_path, trigger_mtime=100, textual_requester=forbidden)
    assert second["attempted"] == []
    assert not second["failed_modes"]
    assert set(second["results"]) == {"unified"}
    forbidden.assert_not_called()


@pytest.mark.parametrize("status", ["pending", "done"])
@pytest.mark.parametrize("structured_output", [False, True])
def test_estado_v1_sem_projecao_preserva_configuracao_e_retomada(config, tmp_path, status, structured_output):
    first = run(config, tmp_path, trigger_mtime=100, structured_output=structured_output)
    path = Path(first["manifest_path"])
    state = legacy_state(json.loads(path.read_text()), config)
    state["modes"]["unified"]["status"] = status
    if status == "pending":
        del state["completed_at"]
    path.write_text(json.dumps(state))
    before = path.read_bytes()
    assert pipeline.should_run_aligned(config, "WEGE3", 100, structured_output=structured_output)[0] == (status == "pending")
    assert path.read_bytes() == before
    assert load_decision_snapshot(path) == state["snapshot"]
    requester = sender if status == "pending" else Mock(side_effect=AssertionError("Sem novo chat."))
    second = run(config, tmp_path, trigger_mtime=100, structured_output=structured_output, textual_requester=requester)
    assert not second["failed_modes"]
    assert second["dataset_id"] == first["dataset_id"]
    assert second["attempted"] == (["unified"] if status == "pending" else [])
    assert pipeline.collect_decision_snapshot.call_count == 1


@pytest.mark.parametrize("status", ["pending", "done"])
def test_troca_de_modelo_em_estado_v1_nao_perde_protecao(config, tmp_path, status):
    first = run(config, tmp_path, trigger_mtime=100)
    path = Path(first["manifest_path"])
    state = legacy_state(json.loads(path.read_text()), config)
    state["modes"]["unified"]["status"] = status
    if status == "pending":
        del state["completed_at"]
    path.write_text(json.dumps(state))
    before = path.read_bytes()
    config.llm_model = "outro"
    if status == "pending":
        with pytest.raises(ValueError, match="Configuracao alterada com execucao pendente"):
            pipeline.should_run_aligned(config, "WEGE3", 100)
    else:
        assert not pipeline.should_run_aligned(config, "WEGE3", 100)[0]
        assert pipeline.should_run_aligned(config, "WEGE3", 101)[0]
    assert path.read_bytes() == before


def test_estado_antigo_com_identidade_corrompida_nao_e_convertido(config, tmp_path):
    first = run(config, tmp_path, trigger_mtime=100)
    path = Path(first["manifest_path"])
    state = legacy_state(json.loads(path.read_text()), config)
    state["identity"] = "corrompida"
    path.write_text(json.dumps(state))
    before = path.read_bytes()
    with pytest.raises(ValueError, match="Identidade"):
        pipeline.should_run_aligned(config, "WEGE3", 100)
    assert path.read_bytes() == before


@pytest.mark.parametrize("change", ["model", "instructions", "transport", "endpoint"])
def test_configuracao_sozinha_nao_reprocessa_concluido(config, tmp_path, monkeypatch, change):
    first = run(config, tmp_path, trigger_mtime=100)
    path = Path(first["manifest_path"])
    original = path.read_bytes()
    args = {}
    if change == "model":
        config.llm_model = "outro"
    elif change == "instructions":
        monkeypatch.setattr(pipeline, "INSTRUCTIONS_VERSION", "outras")
    elif change == "transport":
        args["structured_output"] = True
    else:
        config.ollama_url_base = "http://outro"
    assert not pipeline.should_run_aligned(config, "WEGE3", 100, **args)[0]
    config.report_min_age_hours = 24
    assert not pipeline.should_run_aligned(config, "WEGE3", 101, **args)[0]
    config.report_min_age_hours = 0
    assert pipeline.should_run_aligned(config, "WEGE3", 101, **args)[0]
    assert path.read_bytes() == original


def test_estado_antigo_com_projecao_corrompida_nao_e_ignorado(config, tmp_path):
    first = run(config, tmp_path, trigger_mtime=100)
    path = Path(first["manifest_path"])
    state = legacy_state(json.loads(path.read_text()), config)
    state["models"]["unified_decision"] = config.llm_model
    state["modes"]["unified_decision"] = deepcopy(state["modes"]["unified"])
    state["modes"]["unified_decision"]["result_hash"] = "corrompido"
    path.write_text(json.dumps(state))
    before = path.read_bytes()
    with pytest.raises(ValueError, match="Hash"):
        pipeline.should_run_aligned(config, "WEGE3", 100)
    assert path.read_bytes() == before


def test_estado_antigo_pendente_retoma_so_relatorio(config, tmp_path):
    first = run(config, tmp_path, trigger_mtime=100, textual_requester=lambda p: "{}")
    path = Path(first["manifest_path"])
    state = legacy_state(json.loads(path.read_text()), config)
    state["models"]["unified_decision"] = config.llm_model
    state["modes"]["unified_decision"] = {"status": "pending"}
    path.write_text(json.dumps(state))
    second = run(config, tmp_path, trigger_mtime=100)
    assert second["attempted"] == ["unified"]
    assert not second["failed_modes"]
    saved = json.loads(path.read_text())
    assert saved["version"] == pipeline.VERSION
    assert saved["execution"]["status"] == "done"
    assert "modes" not in saved and "models" not in saved
    assert "decision_model" not in saved["configuration"]
    assert "decision_endpoint" not in saved["configuration"]
    assert saved["snapshot"] == state["snapshot"]
    assert pipeline.collect_decision_snapshot.call_count == 1


@pytest.mark.parametrize("change", ["model", "instructions", "transport"])
def test_configuracao_nao_muda_com_pendencia(config, tmp_path, monkeypatch, change):
    first = run(config, tmp_path, trigger_mtime=100, textual_requester=lambda p: "{}")
    path = Path(first["manifest_path"])
    original = path.read_bytes()
    args = {}
    if change == "model":
        config.llm_model = "outro"
    elif change == "instructions":
        monkeypatch.setattr(pipeline, "INSTRUCTIONS_VERSION", "outras")
    else:
        args["structured_output"] = True
    with pytest.raises(ValueError, match="Configuracao alterada com execucao pendente"):
        pipeline.should_run_aligned(config, "WEGE3", 100, **args)
    assert path.read_bytes() == original


def test_novo_alerta_usa_modelo_atual(config, tmp_path):
    run(config, tmp_path, trigger_mtime=100)
    config.llm_model = "outro"
    second = run(config, tmp_path, trigger_mtime=101)
    assert second["results"]["unified"]["model"] == "outro"
    assert not pipeline.should_run_aligned(config, "WEGE3", 101)[0]


@pytest.mark.parametrize("status", ["done", "pending"])
def test_estado_com_contrato_antigo_nao_e_reescrito_ou_misturado(config, tmp_path, status):
    first = run(config, tmp_path, trigger_mtime=100)
    path = Path(first["manifest_path"])
    state = json.loads(path.read_text())
    state["configuration"]["text_format"] = "baseline-textual-v3-experimental"
    state["configuration"]["unified_format"] = "unified-relatorio-decisao-v2-conciso-experimental"
    state["identity"] = pipeline._digest(state["configuration"])
    result = state["execution"]["result"]
    result["schema_version"] = "assessment-v2"
    result["probability_source"] = "autodeclarada-nao-calibrada"
    for row in result["horizons"].values():
        for item in row.values():
            item.update(confidence=0.7, probabilities={item["class"]: 1.0})
    state["execution"]["result_hash"] = pipeline._digest(result)
    state["execution"]["status"] = status
    if status == "pending":
        del state["completed_at"]
    path.write_text(json.dumps(state))
    before = path.read_bytes()
    if status == "done":
        assert not pipeline.should_run_aligned(config, "WEGE3", 100)[0]
    else:
        with pytest.raises(ValueError, match="Configuracao alterada com execucao pendente"):
            pipeline.should_run_aligned(config, "WEGE3", 100)
    assert path.read_bytes() == before
    assert pipeline.collect_decision_snapshot.call_count == 1


def test_manual_separado_e_replay_sem_recoleta(config, tmp_path, monkeypatch):
    queued = run(config, tmp_path, trigger_mtime=100)
    path = Path(queued["manifest_path"])
    before = path.read_bytes()
    monkeypatch.setattr(pipeline, "collect_decision_snapshot", Mock(side_effect=AssertionError("Sem recoleta.")))
    manual = run(config, tmp_path, snapshot_path=str(path))
    assert Path(manual["manifest_path"]).name == "WEGE3.manual.json"
    assert path.read_bytes() == before


@pytest.mark.parametrize("damage", ["hash", "snapshot", "version", "missing_result", "external", "old_pair"])
def test_estado_invalido_nao_e_recoletado(config, tmp_path, damage):
    first = run(config, tmp_path, trigger_mtime=100)
    path = Path(first["manifest_path"])
    state = json.loads(path.read_text())
    if damage == "hash":
        state["execution"]["result_hash"] = "alterado"
    elif damage == "snapshot":
        state["snapshot"]["ticker"] = "ABEV3"
    elif damage == "version":
        state["version"] = "desconhecida"
    elif damage == "missing_result":
        del state["execution"]["result"]
    elif damage == "external":
        state["execution"]["result_path"] = "/tmp/externo"
    else:
        state["models"] = {"decision": "antigo", "report": config.llm_model}
    path.write_text(json.dumps(state))
    original = path.read_bytes()
    with pytest.raises(ValueError):
        pipeline.should_run_aligned(config, "WEGE3", 100)
    assert path.read_bytes() == original
    assert pipeline.collect_decision_snapshot.call_count == 1


def test_evento_atualizado_mantem_elegibilidade(config, tmp_path, monkeypatch):
    run(config, tmp_path, trigger_mtime=100)
    config.llm_model = "outro"
    monkeypatch.setattr(pipeline, "load_event_context", lambda *a: {"token": "novo"})
    monkeypatch.setattr(pipeline, "event_token", lambda c: c["token"])
    assert pipeline.should_run_aligned(config, "WEGE3", 100)[0]


def test_insuficiencia_sem_chamada(config, tmp_path, snapshot):
    snapshot["evidence"] = {}
    pipeline.collect_decision_snapshot.return_value = snapshot
    requester = Mock(side_effect=AssertionError("Sem chamada."))
    assert not run(config, tmp_path, textual_requester=requester)["failed_modes"]
    requester.assert_not_called()


@pytest.mark.parametrize("provider", ["ollama", "openai"])
def test_esquema_e_metadados_mantidos(config, tmp_path, monkeypatch, provider):
    from b3_report.llm import LLMResponse
    seen = []
    if provider == "openai":
        config.openai_url_base = "http://simulado/v1"
        config.ollama_url_base = ""
    def chat(prompt, **kwargs):
        seen.append(kwargs)
        return LLMResponse(sender(prompt), {"done": True, "done_reason": "stop"})
    monkeypatch.setattr(pipeline, "get_investment_analysis", chat)
    result = pipeline.run_aligned("WEGE3", config=config, trigger_mtime=100,
                                  reports_dir=str(tmp_path / "reports"), structured_output=True)
    assert not result["failed_modes"]
    assert len(seen) == 2 and all(x["response_schema"] for x in seen)
    assert all(x["model"] == config.llm_model and x["api_key"] == config.llm_api_key
               and x["openai_url_base"] == config.openai_url_base
               and x["ollama_url_base"] == config.ollama_url_base for x in seen)
    assert result["results"]["unified"]["stages"][0]["response_metadata"]["done"]


def test_configuracao_ambigua_falha_antes_da_coleta(config, tmp_path):
    from b3_report.llm import LLMConfigurationError
    config.openai_url_base = "http://simulado/v1"
    with pytest.raises(LLMConfigurationError, match="exatamente uma"):
        run(config, tmp_path)
    pipeline.collect_decision_snapshot.assert_not_called()


def test_configuracao_atual_sem_campos_do_modelo_removido(config, tmp_path):
    from b3_report.model_state import MODEL_STATE_VERSION
    from b3_report.unified import UNIFIED_FORMAT_VERSION
    expected = {"version": pipeline.VERSION, "report_model": config.llm_model,
                "report_endpoint": config.openai_url_base or config.ollama_url_base,
                "rubric": pipeline.RUBRIC_VERSION, "instructions": pipeline.INSTRUCTIONS_VERSION,
                "normalization_policy": pipeline.NORMALIZATION_POLICY, "model_state_version": MODEL_STATE_VERSION,
                "event_policy": pipeline.AUTO_EVENT_POLICY_VERSION,
                "text_format": pipeline.BASELINE_FORMAT_VERSION, "unified_format": UNIFIED_FORMAT_VERSION}
    assert pipeline._configuration(config) == expected
    assert pipeline._identity(config) == pipeline._digest(expected)


def test_checkpoint_interrompido_nao_marca_concluido(config, tmp_path, monkeypatch):
    writer = pipeline.write_report_file_atomic
    def interrupted(path, content):
        if Path(path).name.endswith(".queue.json") and json.loads(content)["execution"]["status"] == "done":
            raise OSError("Checkpoint interrompido")
        return writer(path, content)
    monkeypatch.setattr(pipeline, "write_report_file_atomic", interrupted)
    with pytest.raises(OSError, match="Checkpoint interrompido"):
        run(config, tmp_path, trigger_mtime=100)
    state = json.loads(pipeline.aligned_job_path(config, "WEGE3").read_text())
    assert state["execution"] == {"status": "pending"}
