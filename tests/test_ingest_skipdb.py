import json
from unittest.mock import patch, MagicMock

from b3_etl.ingest import run_ingest
from b3_core.config import load_config


def _mock_brapi_response(ticker="PETR4"):
    return {
        "results": [{
            "shortName": ticker,
            "currency": "BRL",
            "regularMarketPrice": 35.0,
            "regularMarketTime": 1700000000,
            "regularMarketOpen": 34.5,
            "regularMarketDayHigh": 35.5,
            "regularMarketDayLow": 34.0,
            "regularMarketVolume": 1000000,
            "financialData": {"totalRevenue": 1000000.0},
        }]
    }


def test_skip_db_nao_levanta_name_error(tmp_path, capsys):
    config = load_config()
    config = config.__class__(
        **{**config.__dict__, "raw_dir": str(tmp_path / "raw")}
    )
    with patch("b3_etl.ingest.fetch_quote", return_value=_mock_brapi_response()):
        result = run_ingest(
            tickers=["PETR4"],
            config=config,
            modules=["financialData"],
            write_snapshot=False,
            skip_db=True,
        )
    assert result == 0


def test_log_json_emitido_no_sucesso(tmp_path, capsys):
    config = load_config()
    config = config.__class__(
        **{**config.__dict__, "raw_dir": str(tmp_path / "raw")}
    )
    with patch("b3_etl.ingest.fetch_quote", return_value=_mock_brapi_response()):
        run_ingest(
            tickers=["PETR4"],
            config=config,
            modules=["financialData"],
            write_snapshot=False,
            skip_db=True,
        )
    lines = [l for l in capsys.readouterr().out.strip().splitlines() if l]
    logs = [json.loads(l) for l in lines]
    jobs = [l["job"] for l in logs]
    assert "etl_start" in jobs
    ticker_logs = [l for l in logs if l.get("job") == "etl_ticker"]
    assert len(ticker_logs) == 1
    assert ticker_logs[0]["ticker"] == "PETR4"
    assert "rows_fundamentals" in ticker_logs[0]
    assert ticker_logs[0]["rows_prices"] == 0  # skip_db=True, nenhum preço gravado no DB
    assert "duration_ms" in ticker_logs[0]
