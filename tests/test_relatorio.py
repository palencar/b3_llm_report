from pathlib import Path
import runpy
from unittest.mock import patch

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "relatorio"


@pytest.fixture
def cli():
    with patch("socket.socket.connect", side_effect=AssertionError("Rede bloqueada")), \
         patch("socket.create_connection", side_effect=AssertionError("Rede bloqueada")):
        yield runpy.run_path(str(SCRIPT))["main"]


@pytest.fixture
def report(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / "reports"
    directory.mkdir()
    path = directory / "WEGE3.md"
    path.write_text('---\nsimbolo: "WEGE3"\n---\n\n# Relatorio\n', encoding="utf-8")
    return path


@pytest.mark.parametrize("flag", [None, "--somente-conteudo", "--somente-caminho"])
def test_consulta_conteudo_e_caminho(cli, report, capsys, flag):
    before = report.stat().st_mtime_ns
    args = ["consultar", "wege3"] + ([flag] if flag else [])
    assert cli(args) == 0
    captured = capsys.readouterr()
    if flag == "--somente-caminho":
        assert captured.out == f"{report}\n"
    else:
        assert captured.out == report.read_text(encoding="utf-8")
    assert captured.err == (f"Relatorio: {report}\n" if flag is None else "")
    assert report.stat().st_mtime_ns == before
    assert sorted(p.relative_to(report.parent.parent).as_posix()
                  for p in report.parent.parent.rglob("*")) == ["reports", "reports/WEGE3.md"]


def test_diretorio_explicito_independente_do_cwd(cli, report, tmp_path, monkeypatch, capsys):
    other = tmp_path / "outro"
    other.mkdir()
    monkeypatch.chdir(other)
    assert cli(["consultar", "WEGE3", "--diretorio-relatorios", str(report.parent),
                "--somente-caminho"]) == 0
    assert capsys.readouterr().out == f"{report}\n"


@pytest.mark.parametrize("flag", [[], ["--somente-conteudo"], ["--somente-caminho"]])
def test_relatorio_ausente_nao_cria_diretorios(cli, tmp_path, monkeypatch, capsys, flag):
    monkeypatch.chdir(tmp_path)
    assert cli(["consultar", "WEGE3", *flag]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Relatorio nao encontrado para WEGE3" in captured.err
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("args", [
    [], ["gerar", "../WEGE3"], ["consultar", "../WEGE3"],
    ["consultar", "WEGE3", "--somente-conteudo", "--somente-caminho"],
    ["consultar", "WEGE3/"], ["consultar", "A"], ["consultar", "ABCDEFG"],
])
def test_argumentos_invalidos(cli, args, capsys):
    with pytest.raises(SystemExit) as exc:
        cli(args)
    assert exc.value.code == 2
    assert capsys.readouterr().out == ""


def test_diretorio_nao_e_relatorio(cli, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "reports" / "WEGE3.md").mkdir(parents=True)
    assert cli(["consultar", "WEGE3"]) == 1
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("error", [PermissionError("Sem permissao"), UnicodeError("UTF-8 invalido")])
def test_falha_de_leitura_nao_imprime_caminho_de_sucesso(cli, report, capsys, error):
    with patch.object(Path, "read_text", side_effect=error):
        assert cli(["consultar", "WEGE3"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Falha ao consultar relatorio de WEGE3" in captured.err
    assert "Relatorio:" not in captured.err


def test_somente_caminho_nao_le_conteudo(cli, report, capsys):
    with patch.object(Path, "read_text", side_effect=AssertionError("Leitura desnecessaria")):
        assert cli(["consultar", "WEGE3", "--somente-caminho"]) == 0
    assert capsys.readouterr().out == f"{report}\n"


def test_conteudo_sem_quebra_final_e_preservado(cli, report, capsys):
    report.write_text("Relatorio sem quebra final", encoding="utf-8")
    assert cli(["consultar", "WEGE3", "--somente-conteudo"]) == 0
    assert capsys.readouterr().out == "Relatorio sem quebra final"


def test_gerar_cria_solicitacao_sem_docker_e_sem_alterar_relatorio(cli, report, capsys):
    from b3_report.queue_control import read_request

    content = report.read_bytes()
    assert cli(["gerar", "wege3"]) == 0
    request = read_request("queue", "WEGE3")
    assert request is not None
    assert report.read_bytes() == content
    captured = capsys.readouterr()
    assert "Solicitacao registrada para WEGE3" in captured.out
    assert "Estado do servico nao verificado" in captured.out
    assert captured.err == ""


def test_gerar_repetido_preserva_solicitacao(cli, tmp_path, capsys):
    from b3_report.queue_control import request_path

    queue = tmp_path / "fila"
    args = ["gerar", "WEGE3", "--diretorio-fila", str(queue)]
    assert cli(args) == 0
    path = request_path(queue, "WEGE3")
    before = path.read_bytes(), path.stat().st_mtime_ns
    assert cli(args) == 0
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert "Solicitacao ja registrada" in capsys.readouterr().out


def test_gerar_com_ativo_bloqueado_nao_enfileira(cli, tmp_path, capsys):
    from b3_report.queue_control import processing_lock, request_path

    queue = tmp_path / "fila"
    with processing_lock(queue, "WEGE3"):
        assert cli(["gerar", "WEGE3", "--diretorio-fila", str(queue)]) == 0
    assert not request_path(queue, "WEGE3").exists()
    assert "nenhuma nova solicitacao criada" in capsys.readouterr().out


def test_gerar_aguarda_controle_curto_e_persiste_pedido(cli, tmp_path, capsys):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from b3_report.queue_control import read_request, request_lock

    waiting = Event()
    def observe_lock(*args, **kwargs):
        waiting.set()
        return request_lock(*args, **kwargs)
    with ThreadPoolExecutor(max_workers=1) as executor:
        with request_lock(tmp_path, "WEGE3"), \
             patch("b3_report.queue_control.request_lock", side_effect=observe_lock):
            future = executor.submit(cli, ["gerar", "WEGE3", "--diretorio-fila", str(tmp_path)])
            assert waiting.wait(timeout=5)
            assert not future.done()
            assert read_request(tmp_path, "WEGE3") is None
        assert future.result(timeout=5) == 0
    assert read_request(tmp_path, "WEGE3") is not None
    captured = capsys.readouterr()
    assert "Solicitacao registrada" in captured.out
    assert "ja esta em processamento" not in captured.out


def test_registros_concorrentes_sao_agrupados(cli, tmp_path, capsys):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from b3_report.queue_control import read_request

    barrier = Barrier(2)
    def submit():
        barrier.wait(timeout=5)
        return cli(["gerar", "WEGE3", "--diretorio-fila", str(tmp_path)])
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(submit) for _ in range(2)]
        assert [future.result(timeout=5) for future in futures] == [0, 0]
    assert read_request(tmp_path, "WEGE3") is not None
    captured = capsys.readouterr()
    assert captured.out.count("Solicitacao registrada") == 1
    assert captured.out.count("Solicitacao ja registrada") == 1
    assert "em processamento" not in captured.out


def test_gerar_solicitacao_corrompida_nao_substitui(cli, tmp_path, capsys):
    from b3_report.queue_control import request_path

    path = request_path(tmp_path, "WEGE3")
    path.parent.mkdir()
    path.write_text("{")
    assert cli(["gerar", "WEGE3", "--diretorio-fila", str(tmp_path)]) == 1
    assert path.read_text() == "{"
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Falha ao solicitar relatorio" in captured.err
