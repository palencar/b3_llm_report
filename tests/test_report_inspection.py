from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from b3_report import cli


def test_resumo_sem_dados_nao_habilita_impressao():
    text, has_data = cli.inspection_summary("PETR4", "", "", None)
    assert has_data is False
    assert "Resumo de Dados (PETR4)" in text
    assert "Total de campos preenchidos: 0" in text
    assert "Fundamentus" in text and "CVM" in text


def test_resumo_yfinance_conta_somente_campos_preenchidos():
    source = ("Relatorio da acao\nBasicos\n- Nome: Empresa\n- Site: N/A\n"
              "- Setor: None\n- Outro: nan\n\nPreco\n- Atual: 10.0\n")
    text, has_data = cli.inspection_summary("PETR4", source, "", None)
    assert has_data is True
    assert "Total de campos preenchidos: 2" in text
    assert "Basicos: 1 campos" in text and "Preco: 1 campos" in text


def test_resumo_fundamentus_conta_metricas_por_secao():
    source = "Dados de Mercado\n- Preco: 10\n- Volume: 100\nRentabilidade\n- ROE: 12%\n"
    text, has_data = cli.inspection_summary("PETR4", "", source, None)
    assert has_data is True
    assert "3 m\u00e9tricas preenchidas" in text
    assert "Dados de Mercado: 2 m\u00e9tricas" in text
    assert "Rentabilidade: 1 m\u00e9tricas" in text


def test_resumo_cvm_agrupa_linhas_por_demonstrativo():
    rows = [("2025-12-31", "BPA"), ("2025-12-31", "BPA"), ("2025-12-31", "DRE")]
    text, has_data = cli.inspection_summary("PETR4", "", "", rows)
    assert has_data is True
    assert "2 tipos de demonstrativo (3 linhas)" in text
    assert "Balan\u00e7o Patrimonial Ativo: 2 linhas" in text
    assert "Demonstra\u00e7\u00e3o do Resultado: 1 linhas" in text


@pytest.mark.parametrize("cvm_falha", [False, True])
def test_relatorio_imprime_resumo_sem_alterar_prompt_ou_publicacao(tmp_path, monkeypatch, capsys, cvm_falha):
    monkeypatch.chdir(tmp_path)
    config = SimpleNamespace(llm_model="simulado", llm_api_key="",
                             openai_url_base="", ollama_url_base="http://simulado",
                             db_path=str(tmp_path / "simulado.duckdb"), fund_ttl=86400,
                             report_history_n=4, raw_dir=str(tmp_path / "raw"), corporate_events_file="")
    monkeypatch.setattr(cli, "load_dotenv", Mock())
    monkeypatch.setattr(cli, "load_config", Mock(return_value=config))
    monkeypatch.setattr(cli, "load_event_context", Mock(return_value=None))
    yf_text = "Basicos\n- Nome: Empresa simulada\n"
    for name, value in (("get_yfinance_data", yf_text), ("get_complementary_data", ""),
                        ("get_cvm_data", "CVM simulado"), ("get_recent_reports_history", "")):
        monkeypatch.setattr(cli, name, Mock(return_value=value))
    rows = Mock(side_effect=OSError("Falha simulada")) if cvm_falha else Mock(return_value=[("2025-12-31", "BPA")])
    monkeypatch.setattr(cli, "fetch_raw_rows", rows)
    prompt = Mock(return_value="PROMPT")
    monkeypatch.setattr(cli, "prepare_llm_investment_analysis_request", prompt)
    report = ("#### Identifica\u00e7\u00e3o\n- Empresa: Empresa simulada\n- Data da An\u00e1lise: "
              + datetime.now().strftime("%Y-%m-%d")
              + "\n#### Resumo\n##### Curt\u00edssimo Prazo\n##### Curto Prazo\n##### M\u00e9dio Prazo\n")
    sender = Mock(return_value=report)
    monkeypatch.setattr(cli, "get_investment_analysis", sender)
    assert cli.run_report("PETR4") == report
    out = capsys.readouterr().out
    assert "Resumo de Dados (PETR4)" in out
    assert ("indispon\u00edvel" in out) is cvm_falha
    rows.assert_called_once_with("PETR4", config.db_path)
    sender.assert_called_once()
    assert sender.call_args.args == ("PROMPT",)
    assert prompt.call_args.args[0] == yf_text
    assert prompt.call_args.kwargs["cvm_info"] == "CVM simulado"
    assert (tmp_path / "reports" / "PETR4.md").read_text(encoding="utf-8") == report
