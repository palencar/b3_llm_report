"""Contagens informadas pelos servidores, sem estimar tokens nem repetir chamadas."""

from contextlib import contextmanager
from contextvars import ContextVar


_CALLS = ContextVar("b3_token_calls", default=None)


def _count(value):
    return value if type(value) is int and value >= 0 else None


def _display(value):
    return str(value) if value is not None else "indisponivel"


def report_token_usage(provider, model, *, input_tokens=None, output_tokens=None, total_tokens=None):
    incoming, outgoing, total = map(_count, (input_tokens, output_tokens, total_tokens))
    if total is None and incoming is not None and outgoing is not None:
        total = incoming + outgoing
    label = " ".join(f"{provider} modelo={model}".split())
    print(f"Tokens da chamada ({label}): entrada={_display(incoming)}; "
          f"saida={_display(outgoing)}; total={_display(total)}", flush=True)
    calls = _CALLS.get()
    if calls is not None:
        calls.append((incoming, outgoing, total))


def _sum_display(values):
    known = [value for value in values if value is not None]
    if len(known) != len(values):
        return f"indisponivel (subtotal conhecido={sum(known)})"
    return str(sum(known))


@contextmanager
def token_usage_session():
    """Soma chamadas novas da execucao; sessoes aninhadas nao duplicam contagens."""
    if _CALLS.get() is not None:
        yield
        return
    calls = []
    token = _CALLS.set(calls)
    try:
        yield
    finally:
        _CALLS.reset(token)
        if len(calls) > 1:
            incoming, outgoing, total = (_sum_display([call[i] for call in calls]) for i in range(3))
            print(f"Tokens da execucao: chamadas={len(calls)}; entrada={incoming}; "
                  f"saida={outgoing}; total={total}", flush=True)
