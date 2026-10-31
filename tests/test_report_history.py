from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from b3_report.cli import ReportValidationError, _validate_report_content, run_report
from b3_report.llm import LLMRequestError

from b3_report.reports import (
    get_recent_reports_history,
    save_report_snapshot,
    write_report_file_atomic,
)


def test_get_recent_reports_history_retorna_mais_recentes(tmp_path):
    report_dir = tmp_path / "reports"
    history_dir = report_dir / "PETR4"
    history_dir.mkdir(parents=True)
    (history_dir / "2026-03-20_090000.md").write_text("Relatorio 20", encoding="utf-8")
    (history_dir / "2026-03-21_090000.md").write_text("Relatorio 21", encoding="utf-8")
    (history_dir / "2026-03-22_090000.md").write_text("Relatorio 22", encoding="utf-8")

    result = get_recent_reports_history("PETR4", report_dir=str(report_dir), n=2)

    assert "Relatorio 22" in result
    assert "Relatorio 21" in result
    assert "Relatorio 20" not in result
    assert result.index("Relatorio 22") < result.index("Relatorio 21")


def test_get_recent_reports_history_ignora_nome_fora_do_contrato(tmp_path, caplog):
    report_dir = tmp_path / "reports"
    history_dir = report_dir / "PETR4"
    history_dir.mkdir(parents=True)
    (history_dir / "invalido.md").write_text("conteudo", encoding="utf-8")

    result = get_recent_reports_history("PETR4", report_dir=str(report_dir), n=2)

    assert result == ""
    assert "Arquivo de historico ignorado por nome fora do contrato" in caplog.text


def test_save_report_snapshot_cria_arquivo_versionado(tmp_path):
    report_dir = tmp_path / "reports"

    snapshot_path = save_report_snapshot(
        ticker="PETR4",
        content="relatorio",
        analysis_timestamp=datetime(2026, 3, 26, 8, 15, 0),
        report_dir=str(report_dir),
    )

    assert snapshot_path == report_dir / "_history" / "PETR4" / "2026-03-26_081500.md"
    assert snapshot_path.read_text(encoding="utf-8") == "relatorio"


def test_write_report_file_atomic_sobrescreve_arquivo_final(tmp_path):
    target_path = tmp_path / "reports" / "PETR4.md"
    target_path.parent.mkdir(parents=True)
    target_path.write_text("conteudo antigo", encoding="utf-8")

    write_report_file_atomic(target_path, "conteudo novo")

    assert target_path.read_text(encoding="utf-8") == "conteudo novo"


def test_save_report_snapshot_usa_diretorio_alternativo_quando_arquivo_legado_existe(tmp_path, caplog):
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    (report_dir / "MXRF11").write_text("legado", encoding="utf-8")

    snapshot_path = save_report_snapshot(
        ticker="MXRF11",
        content="relatorio",
        analysis_timestamp=datetime(2026, 4, 21, 11, 39, 11),
        report_dir=str(report_dir),
    )

    assert snapshot_path == report_dir / "_history" / "MXRF11" / "2026-04-21_113911.md"
    assert "conflita com arquivo existente" in caplog.text


def test_get_recent_reports_history_usa_arquivo_corrente_quando_nao_ha_snapshots(tmp_path):
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    (report_dir / "MXRF11.md").write_text("relatorio corrente", encoding="utf-8")

    result = get_recent_reports_history("MXRF11", report_dir=str(report_dir), n=4)

    assert "relatorio corrente" in result
    assert "MXRF11.md" in result


VALID_REPORT = """#### Identificação
- Empresa: PETROBRAS S.A.
- Data da Análise: 2026-03-26

#### Resumo
- Recomendação Geral: Compra

#### Análise por Horizonte
##### Curtíssimo Prazo
- Perspectiva: Positiva

##### Curto Prazo
- Perspectiva: Positiva

##### Médio Prazo
- Perspectiva Estratégica: Positiva
"""


def test_run_report_nao_persiste_ao_receber_erro_do_llm(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    config = SimpleNamespace(
        db_path=str(tmp_path / "db.duckdb"),
        llm_api_key="key",
        openai_url_base="http://localhost:11434/v1",
        ollama_url_base="",
        llm_model="llama3.1",
        report_history_n=4,
        fund_ttl=86400,
    )

    with patch("b3_report.cli.load_dotenv"), \
         patch("b3_report.cli.load_config", return_value=config), \
         patch("b3_report.cli.get_yfinance_data", return_value="dados yf"), \
         patch("b3_report.cli.get_complementary_data", return_value="dados fund"), \
         patch("b3_report.cli.get_cvm_data", return_value="dados cvm"), \
         patch("b3_report.cli.prepare_llm_investment_analysis_request", return_value="PROMPT"), \
         patch("b3_report.cli.get_investment_analysis", side_effect=LLMRequestError("Erro ao fazer chamada ao Ollama: timeout")):
        try:
            run_report("petr4")
            assert False, "Era esperado erro do LLM"
        except LLMRequestError:
            pass

    assert not (tmp_path / "reports" / "PETR4.md").exists()
    assert not (tmp_path / "reports" / "PETR4").exists()
    assert not (tmp_path / "reports" / "_history" / "PETR4").exists()


def test_run_report_nao_persiste_resposta_invalida(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    current_report = tmp_path / "reports" / "PETR4.md"
    current_report.parent.mkdir(parents=True)
    current_report.write_text("relatorio anterior", encoding="utf-8")

    config = SimpleNamespace(
        db_path=str(tmp_path / "db.duckdb"),
        llm_api_key="key",
        openai_url_base="http://localhost:11434/v1",
        ollama_url_base="",
        llm_model="llama3.1",
        report_history_n=4,
        fund_ttl=86400,
    )

    with patch("b3_report.cli.load_dotenv"), \
         patch("b3_report.cli.load_config", return_value=config), \
         patch("b3_report.cli.get_yfinance_data", return_value="dados yf"), \
         patch("b3_report.cli.get_complementary_data", return_value="dados fund"), \
         patch("b3_report.cli.get_cvm_data", return_value="dados cvm"), \
         patch("b3_report.cli.prepare_llm_investment_analysis_request", return_value="PROMPT"), \
         patch("b3_report.cli.get_investment_analysis", return_value="texto curto sem estrutura"), \
         patch("b3_report.cli.datetime") as mock_datetime:
        mock_datetime.now.return_value = datetime(2026, 3, 26, 8, 15, 0)
        try:
            run_report("petr4")
            assert False, "Era esperado erro de validacao"
        except RuntimeError as exc:
            assert "fora do formato esperado" in str(exc)

    assert current_report.read_text(encoding="utf-8") == "relatorio anterior"
    assert not (tmp_path / "reports" / "PETR4" / "2026-03-26_081500.md").exists()
    assert not (tmp_path / "reports" / "_history" / "PETR4" / "2026-03-26_081500.md").exists()


def test_validate_report_content_exige_identificacao_inicial_com_data_exata():
    report = VALID_REPORT.replace("2026-03-26", "2026-03-25")

    try:
        _validate_report_content(report, "PETR4", "2026-03-26")
        assert False, "Era esperado erro de validacao"
    except ReportValidationError as exc:
        assert "identificacao inicial ausente ou incompleta" in str(exc)


def test_run_report_inclui_historico_e_persiste_snapshot(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    history_dir = tmp_path / "reports" / "PETR4"
    history_dir.mkdir(parents=True)
    previous_snapshot = history_dir / "2026-03-25_090000.md"
    previous_snapshot.write_text("Analise anterior", encoding="utf-8")
    structured = tmp_path / "reports" / "PETR4.json"
    structured.write_text('{"relatorio": "anterior"}', encoding="utf-8")

    config = SimpleNamespace(
        db_path=str(tmp_path / "db.duckdb"),
        llm_api_key="key",
        openai_url_base="http://localhost:11434/v1",
        ollama_url_base="",
        llm_model="llama3.1",
        report_history_n=4,
        fund_ttl=86400,
    )

    with patch("b3_report.cli.load_dotenv"), \
         patch("b3_report.cli.load_config", return_value=config), \
         patch("b3_report.cli.get_yfinance_data", return_value="dados yf"), \
         patch("b3_report.cli.get_complementary_data", return_value="dados fund"), \
         patch("b3_report.cli.get_cvm_data", return_value="dados cvm"), \
         patch("b3_report.cli.prepare_llm_investment_analysis_request", return_value="PROMPT") as mock_prompt, \
         patch("b3_report.cli.get_investment_analysis", return_value=VALID_REPORT), \
         patch("b3_report.cli.datetime") as mock_datetime:
        mock_datetime.now.return_value = datetime(2026, 3, 26, 8, 15, 0)

        result = run_report("petr4")

    assert result == VALID_REPORT
    assert mock_prompt.call_args.kwargs["history_reports"]
    assert "Analise anterior" in mock_prompt.call_args.kwargs["history_reports"]
    assert (tmp_path / "reports" / "PETR4.md").read_text(encoding="utf-8") == VALID_REPORT
    assert not structured.exists()
    assert (tmp_path / "reports" / "PETR4" / "2026-03-26_081500.md").read_text(encoding="utf-8") == VALID_REPORT
