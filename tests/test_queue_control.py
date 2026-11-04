import json
import subprocess
import sys

import pytest

from b3_report.queue_control import (
    TickerBusy, enqueue_request, processing_lock, read_request, request_path,
)


def test_lock_persistente_liberado_por_excecao(tmp_path):
    with pytest.raises(RuntimeError, match="simulada"):
        with processing_lock(tmp_path, "WEGE3"):
            with pytest.raises(TickerBusy):
                with processing_lock(tmp_path, "WEGE3"):
                    pytest.fail("Bloqueio nao respeitado")
            raise RuntimeError("simulada")
    with processing_lock(tmp_path, "WEGE3"):
        assert (tmp_path / ".locks" / "WEGE3").exists()


def test_lock_independente_por_ativo(tmp_path):
    with processing_lock(tmp_path, "WEGE3"), processing_lock(tmp_path, "ABEV3"):
        assert enqueue_request(tmp_path, "ABEV3")
    assert read_request(tmp_path, "ABEV3") is not None


def test_morte_do_processo_libera_lock_sem_remover_arquivo(tmp_path):
    path = tmp_path / ".locks" / "WEGE3"
    path.parent.mkdir()
    code = "import fcntl,sys; f=open(sys.argv[1],'a'); fcntl.flock(f,fcntl.LOCK_EX); print('pronto',flush=True); sys.stdin.read()"
    process = subprocess.Popen([sys.executable, "-c", code, str(path)],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == "pronto"
        with pytest.raises(TickerBusy):
            with processing_lock(tmp_path, "WEGE3"):
                pytest.fail("Processo concorrente ignorado")
    finally:
        process.kill()
        process.communicate(timeout=5)
    with processing_lock(tmp_path, "WEGE3"):
        assert path.exists()


@pytest.mark.parametrize("payload", [
    [], {"id": "x", "requested_at": 1}, {"id": "a" * 32, "requested_at": True},
    {"id": "a" * 32, "requested_at": float("nan")},
    {"id": "a" * 32, "requested_at": 1, "extra": "invalido"},
])
def test_solicitacao_fora_do_contrato_e_preservada(tmp_path, payload):
    path = request_path(tmp_path, "WEGE3")
    path.parent.mkdir()
    path.write_text(json.dumps(payload))
    before = path.read_bytes()
    with pytest.raises(ValueError):
        read_request(tmp_path, "WEGE3")
    assert path.read_bytes() == before


def test_solicitacao_symlink_nao_e_aceita(tmp_path):
    path = request_path(tmp_path, "WEGE3")
    path.parent.mkdir()
    path.symlink_to(tmp_path / "fora")
    with pytest.raises(ValueError, match="link simbolico"):
        read_request(tmp_path, "WEGE3")
