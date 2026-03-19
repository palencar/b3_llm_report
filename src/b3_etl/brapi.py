import json
import time
import urllib.parse
import urllib.request


class BrapiError(Exception):
    pass


def _build_url(base_url: str, ticker: str, modules: list[str], token: str) -> str:
    base = base_url.rstrip("/")
    params = {}
    if modules:
        params["modules"] = ",".join(modules)
    if token:
        params["token"] = token
    query = urllib.parse.urlencode(params)
    return f"{base}/quote/{ticker}?{query}"


def fetch_quote(
    ticker: str,
    modules: list[str],
    base_url: str,
    token: str,
    timeout: int = 30,
) -> dict:
    url = _build_url(base_url, ticker, modules, token)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "b3-llm-report/etl",
            "Accept": "application/json",
        },
        method="GET",
    )
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                payload = response.read().decode("utf-8")
            data = json.loads(payload)
            break
        except Exception as exc:
            if attempt < max_attempts - 1:
                time.sleep(2)
            else:
                raise BrapiError(f"Falha ao consultar BRAPI para {ticker}: {exc}") from exc

    if not isinstance(data, dict) or "results" not in data:
        raise BrapiError(f"Resposta BRAPI invalida para {ticker}")
    return data
