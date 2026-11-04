"""Solicitacoes manuais e exclusao mutua por ativo na fila local Linux."""

from contextlib import contextmanager
import fcntl
import json
import math
from pathlib import Path
import re
import time
from uuid import uuid4

from b3_report.reports import write_report_file_atomic


class TickerBusy(RuntimeError):
    """Outro processo detem o bloqueio desse ativo."""


def request_path(queue_dir, ticker):
    return Path(queue_dir) / ".requests" / f"{ticker}.json"


@contextmanager
def processing_lock(queue_dir, ticker):
    """Nao remover o arquivo: todos os processos devem bloquear o mesmo inode."""
    if re.fullmatch(r"[A-Z0-9]{3,6}", ticker) is None:
        raise ValueError("Simbolo invalido para controle da fila.")
    path = Path(queue_dir) / ".locks" / ticker
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise TickerBusy(ticker) from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def read_request(queue_dir, ticker):
    path = request_path(queue_dir, ticker)
    if path.is_symlink():
        raise ValueError(f"Solicitacao nao pode ser link simbolico: {path}")
    try:
        request = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    if (not isinstance(request, dict) or set(request) != {"id", "requested_at"}
            or not isinstance(request["id"], str)
            or re.fullmatch(r"[0-9a-f]{32}", request["id"]) is None
            or type(request["requested_at"]) not in (float, int)
            or not math.isfinite(request["requested_at"])):
        raise ValueError(f"Solicitacao manual invalida: {path}")
    return request


def enqueue_request(queue_dir, ticker):
    """Chamador deve deter processing_lock durante leitura e gravacao."""
    existing = read_request(queue_dir, ticker)
    if existing is not None:
        return False
    request = {"id": uuid4().hex, "requested_at": time.time()}
    write_report_file_atomic(request_path(queue_dir, ticker), json.dumps(request))
    return True
