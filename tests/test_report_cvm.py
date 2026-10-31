"""Testes para src/b3_report/sources/cvm.py e integração no prompt."""
import pytest
from datetime import datetime, timezone, date

from b3_storage.schema import SCHEMA_SQL
from b3_storage.db import connect
from b3_report.sources.cvm import get_cvm_data


def _init_con(db_path: str):
    con = connect(db_path, read_only=False)
    for stmt in SCHEMA_SQL.split(";"):
        s = stmt.strip()
        if s:
            con.execute(s)
    return con


def _seed_data(con) -> None:
    con.begin()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    con.execute(
        "INSERT INTO ticker_map VALUES (?, ?, ?, ?)",
        ["33000167000101", "PETR", "PETROBRAS", now],
    )
    con.execute(
        "INSERT INTO cvm_companies VALUES (?, ?, ?, ?)",
        ["33.000.167/0001-01", "PETROBRAS S.A.", "9512", now],
    )
    for year in (2022, 2023, 2024):
        period = date(year, 12, 31)
        con.execute(
            "INSERT INTO cvm_statements VALUES (?,?,?,?,?,?,?,?,?)",
            ["33.000.167/0001-01", period, "BPA", "1", "Ativo Total",
             float(100_000_000 * year), "REAL", "cvm_dfp", now],
        )
        con.execute(
            "INSERT INTO cvm_statements VALUES (?,?,?,?,?,?,?,?,?)",
            ["33.000.167/0001-01", period, "BPA", "1.01", "Ativo Circulante",
             float(30_000_000 * year), "REAL", "cvm_dfp", now],
        )
        # nível 3 — deve ser filtrado
        con.execute(
            "INSERT INTO cvm_statements VALUES (?,?,?,?,?,?,?,?,?)",
            ["33.000.167/0001-01", period, "BPA", "1.01.01", "Caixa e Equivalentes",
             float(10_000_000 * year), "REAL", "cvm_dfp", now],
        )
        con.execute(
            "INSERT INTO cvm_statements VALUES (?,?,?,?,?,?,?,?,?)",
            ["33.000.167/0001-01", period, "DRE", "3.01", "Receita Líquida",
             float(50_000_000 * year), "REAL", "cvm_dfp", now],
        )
    con.execute("COMMIT")


def test_get_cvm_data_retorna_texto(tmp_path):
    db = str(tmp_path / "t.duckdb")
    con = _init_con(db)
    _seed_data(con)
    con.close()
    result = get_cvm_data("PETR4", db)
    assert result != ""
    assert "PETR4" in result
    assert "Ativo Total" in result


def test_get_cvm_data_cnpj_zero_a_esquerda(tmp_path):
    """B3 remove zero à esquerda do CNPJ; CVM mantém. O join normaliza p/ 14 dígitos."""
    db = str(tmp_path / "t.duckdb")
    con = _init_con(db)
    con.begin()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    con.execute(
        "INSERT INTO ticker_map VALUES (?, ?, ?, ?)",
        ["2474103000119", "EGIE", "ENGIE BRASIL ENERGIA S.A.", now],
    )
    con.execute(
        "INSERT INTO cvm_companies VALUES (?, ?, ?, ?)",
        ["02.474.103/0001-19", "ENGIE BRASIL ENERGIA S.A.", "17329", now],
    )
    for year in (2023, 2024, 2025):
        con.execute(
            "INSERT INTO cvm_statements VALUES (?,?,?,?,?,?,?,?,?)",
            ["02.474.103/0001-19", date(year, 12, 31), "BPA", "1",
             "Ativo Total", float(100_000_000 * year), "REAL", "cvm_dfp", now],
        )
    con.execute("COMMIT")
    con.close()
    result = get_cvm_data("EGIE3", db)
    assert result != ""
    assert "Ativo Total" in result


def test_get_cvm_data_filtra_nivel_1_2(tmp_path):
    db = str(tmp_path / "t.duckdb")
    con = _init_con(db)
    _seed_data(con)
    con.close()
    result = get_cvm_data("PETR4", db)
    assert "Ativo Total" in result          # nível 1: presente
    assert "Ativo Circulante" in result     # nível 2: presente
    assert "Caixa e Equivalentes" not in result  # nível 3: filtrado


def test_get_cvm_data_tendencia_3_anos(tmp_path):
    db = str(tmp_path / "t.duckdb")
    con = _init_con(db)
    _seed_data(con)
    con.close()
    result = get_cvm_data("PETR4", db)
    assert "2022=" in result
    assert "2023=" in result
    assert "2024=" in result
    assert "|" in result


def test_get_cvm_data_ticker_nao_encontrado(tmp_path):
    db = str(tmp_path / "t.duckdb")
    con = _init_con(db)
    _seed_data(con)
    con.close()
    assert get_cvm_data("XXXX3", db) == ""


def test_get_cvm_data_db_ausente(tmp_path):
    assert get_cvm_data("PETR4", str(tmp_path / "nao_existe.duckdb")) == ""


from b3_report.prompts import prepare_llm_investment_analysis_request


def test_prompt_inclui_secao_cvm():
    prompt = prepare_llm_investment_analysis_request(
        stock_info="dados yf",
        complementary_info="dados fund",
        analysis_date="2026-03-26",
        cvm_info="Demonstrativos CVM Oficiais — PETR4\nAtivo Total...",
    )
    assert "#### Dados CVM (Demonstrativos Oficiais)" in prompt
    assert "Demonstrativos CVM Oficiais — PETR4" in prompt


def test_prompt_omite_secao_cvm():
    prompt = prepare_llm_investment_analysis_request(
        stock_info="dados yf",
        complementary_info="dados fund",
        analysis_date="2026-03-26",
        cvm_info="",
    )
    assert "#### Dados CVM" not in prompt


def test_prompt_inclui_secao_historico():
    prompt = prepare_llm_investment_analysis_request(
        stock_info="dados yf",
        complementary_info="dados fund",
        analysis_date="2026-03-26",
        history_reports="- **2026-03-25 10:00:00** - 2026-03-25_100000.md\nRelatorio anterior",
    )
    assert "#### Histórico de Relatórios Recentes" in prompt
    assert "Relatorio anterior" in prompt


def test_prompt_omite_secao_historico():
    prompt = prepare_llm_investment_analysis_request(
        stock_info="dados yf",
        complementary_info="dados fund",
        analysis_date="2026-03-26",
        history_reports="",
    )
    assert "#### Histórico de Relatórios Recentes" not in prompt


def test_prompt_nao_inclui_disclaimer():
    prompt = prepare_llm_investment_analysis_request(
        stock_info="dados yf",
        complementary_info="dados fund",
        analysis_date="2026-03-26",
    )
    assert "### Disclaimer" not in prompt
    assert "Recomenda-se sempre complementar com análise própria" not in prompt


def test_prompt_exige_portugues_brasileiro_integral():
    prompt = prepare_llm_investment_analysis_request(
        stock_info="dados yf",
        complementary_info="dados fund",
        analysis_date="2026-03-26",
    )
    assert "Responda integralmente em português brasileiro claro, direto e natural" in prompt
    assert "Não use rótulos ou termos em inglês na resposta final" in prompt
    assert "Compra, Manutenção, Venda, Compra em Correção, Neutra" in prompt


def test_prompt_exige_estrutura_fixa_sem_campos_extras():
    prompt = prepare_llm_investment_analysis_request(
        stock_info="dados yf",
        complementary_info="dados fund",
        analysis_date="2026-03-26",
    )
    assert "Siga EXATAMENTE a estrutura e a ordem abaixo" in prompt
    assert "Não adicione seções, subseções, campos ou observações extras" in prompt
    assert 'Não inclua campos adicionais como "Nível de Confusão", "Confiança Justificativa", "Resumo Executivo" ou equivalentes' in prompt


def test_prompt_exige_identificacao_no_inicio():
    prompt = prepare_llm_investment_analysis_request(
        stock_info="Relatório Detalhado da Ação PETR4.SA\n- Nome: PETROBRAS S.A.",
        complementary_info="dados fund",
        analysis_date="2026-03-26",
    )
    assert 'O texto final deve começar pela seção "#### Identificação"' in prompt
    assert "No campo \"Empresa\", informe o nome da empresa conforme os dados fornecidos" in prompt
    assert "No campo \"Data da Análise\", reproduza exatamente: 2026-03-26" in prompt
    assert prompt.index("#### Identificação") < prompt.index("#### Resumo")
    assert "- Data da Análise: 2026-03-26" in prompt


def test_prompt_proibe_extrapolacao_e_limita_tamanho():
    prompt = prepare_llm_investment_analysis_request(
        stock_info="dados yf",
        complementary_info="dados fund",
        analysis_date="2026-03-26",
    )
    assert "Não infira cenário macroeconômico, regulação, fluxo institucional, movimento setorial futuro, juros, câmbio ou catalisadores externos sem dado explícito nas seções fornecidas" in prompt
    assert "Se um ponto depender de informação externa não presente nos dados, registre a limitação em vez de extrapolar" in prompt
    assert "Seja conciso: no máximo 2 frases por campo" in prompt
    assert "Limite o relatório inteiro a aproximadamente 350 palavras" in prompt


def test_prompt_normaliza_vocabulario_financeiro():
    prompt = prepare_llm_investment_analysis_request(
        stock_info="dados yf",
        complementary_info="dados fund",
        analysis_date="2026-03-26",
    )
    assert 'Evite expressões imprecisas ou inadequadas para ações, como: "renda fixa via dividendos", "debitabilidade financeira", "upside", "downside", "pullback", "case"' in prompt
    assert '"perfil de renda/dividendos" no lugar de "renda fixa via dividendos"' in prompt
    assert '"potencial de valorização" no lugar de "upside"' in prompt
    assert '"correção" ou "recuo" no lugar de "pullback"' in prompt


def test_prompt_padroniza_arredondamento_e_apresentacao_numerica():
    prompt = prepare_llm_investment_analysis_request(
        stock_info="dados yf",
        complementary_info="dados fund",
        analysis_date="2026-03-26",
    )
    assert "Padronize a apresentação numérica:" in prompt
    assert "preços, preço-alvo e valores monetários unitários: 2 casas decimais" in prompt
    assert "múltiplos e indicadores por ação: até 2 casas decimais" in prompt
    assert "percentuais: até 1 casa decimal" in prompt
    assert "Evite precisão excessiva como 32.4049, 2.83763 ou percentuais com várias casas decimais" in prompt
