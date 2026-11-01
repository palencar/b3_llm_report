from copy import deepcopy

import pytest

from b3_report.model_state import MODEL_STATE_VERSION, compact_model_state


def snapshot(rows):
    return {"ticker": "ABCB4", "source_data": {"yfinance": {"original": 0},
            "fundamentus": "Texto original", "cvm": rows}, "evidence": {"original": None}}


def test_tabela_reversivel_preserva_linhas_valores_e_snapshot():
    rows = [{"period": "2026-06-30", "report_type": "DRE", "account_code": "3.01",
             "account_name": "Receita líquida", "value": 0},
            {"value": None, "account_name": "Prejuizo", "account_code": "3.11",
             "report_type": "DRE", "period": "2026-06-30"}]
    original = snapshot(rows)
    before = deepcopy(original)
    state = compact_model_state(original)
    table = state["source_data"]["cvm"]
    assert table["encoding"] == MODEL_STATE_VERSION
    assert [dict(zip(table["columns"], row)) for row in table["rows"]] == rows
    assert original == before
    assert state["evidence"] == original["evidence"]
    assert compact_model_state(state) == state
    state["source_data"]["yfinance"]["original"] = 2
    assert original == before


@pytest.mark.parametrize("rows", [[], [{"a": None}, {"b": None}], [{}, {}]])
def test_entrada_sem_tabela_homogenea_nao_perde_informacao(rows):
    assert compact_model_state(snapshot(rows)) == snapshot(rows)


def test_estado_de_risco_recebe_mesma_representacao():
    state = {"snapshot": snapshot([{"a": 1}]), "risk_directions": {"curto": "comprada"}}
    result = compact_model_state(state)
    assert result["snapshot"]["source_data"]["cvm"]["rows"] == [[1]]
    assert result["risk_directions"] == state["risk_directions"]


@pytest.mark.parametrize("state", ["Texto preservado", [1, 2], {"snapshot": "Texto"}, {"source_data": None}])
def test_estado_generico_nao_e_reinterpretado(state):
    assert compact_model_state(state) == state






def test_compactacao_preserva_todas_as_401_linhas_sem_truncar():
    rows = [{"period": "2026-06-30", "report_type": "DRE", "account_code": f"3.{i:03}",
             "account_name": "Conta " + "x" * 100, "value": i} for i in range(401)]
    state = snapshot(rows)
    table = compact_model_state(state)["source_data"]["cvm"]
    assert [dict(zip(table["columns"], row)) for row in table["rows"]] == rows
    assert state["source_data"]["cvm"] == rows
