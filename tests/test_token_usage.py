import pytest

from b3_report.token_usage import report_token_usage, token_usage_session


@pytest.mark.parametrize("incoming,outgoing,total,expected", [
    (12, 5, None, "entrada=12; saida=5; total=17"),
    (12, 5, 20, "entrada=12; saida=5; total=20"),
    (12, 0, None, "entrada=12; saida=0; total=12"),
    (None, None, 20, "entrada=indisponivel; saida=indisponivel; total=20"),
    (12, None, None, "entrada=12; saida=indisponivel; total=indisponivel"),
    (True, -2, "20", "entrada=indisponivel; saida=indisponivel; total=indisponivel"),
])
def test_contagens_informadas_sem_estimativa(capsys, incoming, outgoing, total, expected):
    report_token_usage("simulado", "modelo", input_tokens=incoming, output_tokens=outgoing, total_tokens=total)
    assert expected in capsys.readouterr().out


def test_sessoes_aninhadas_somam_cada_chamada_uma_vez(capsys):
    with token_usage_session():
        report_token_usage("simulado", "a", input_tokens=10, output_tokens=2)
        with token_usage_session():
            report_token_usage("simulado", "b", input_tokens=20, output_tokens=0)
    out = capsys.readouterr().out
    assert out.count("Tokens da chamada") == 2
    assert out.count("Tokens da execucao") == 1
    assert "chamadas=2; entrada=30; saida=2; total=32" in out


def test_dado_ausente_nao_vira_total_zero(capsys):
    with token_usage_session():
        report_token_usage("simulado", "a", input_tokens=10, output_tokens=2)
        report_token_usage("simulado", "a")
    out = capsys.readouterr().out
    assert "total=indisponivel (subtotal conhecido=12)" in out


def test_falha_imprime_total_e_nao_contamina_proxima_execucao(capsys):
    with pytest.raises(RuntimeError):
        with token_usage_session():
            report_token_usage("simulado", "a", input_tokens=10, output_tokens=2)
            report_token_usage("simulado", "a", input_tokens=10, output_tokens=2)
            raise RuntimeError("Falha simulada")
    assert "total=24" in capsys.readouterr().out
    with token_usage_session():
        pass
    assert capsys.readouterr().out == ""
    with token_usage_session():
        report_token_usage("simulado", "b", input_tokens=1, output_tokens=0)
    assert "Tokens da execucao" not in capsys.readouterr().out
