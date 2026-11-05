import argparse
import os
import sys

# Ajusta o path para importar o pacote em src/
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from b3_core.config import load_config
from b3_etl.ingest import run_ingest


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ETL de yfinance e Fundamentus para dados da B3.")
    parser.add_argument(
        "--tickers",
        type=str,
        required=True,
        help="Lista de tickers separados por virgula (ex: PETR4,ITUB4,VALE3).",
    )
    parser.add_argument(
        "--modules",
        type=str,
        default="financialData,balanceSheetHistory,incomeStatementHistory",
        help="Parametro legado separado por virgula, sem efeito na coleta atual.",
    )
    parser.add_argument(
        "--skip-db",
        action="store_true",
        help="Nao gravar no DuckDB (mantem apenas raw files).",
    )
    parser.add_argument(
        "--skip-snapshot",
        action="store_true",
        help="Nao gerar snapshots Parquet.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    config = load_config()
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    modules = [m.strip() for m in args.modules.split(",") if m.strip()]

    return run_ingest(
        tickers=tickers,
        config=config,
        modules=modules,
        write_snapshot=not args.skip_snapshot,
        skip_db=args.skip_db,
    )


if __name__ == "__main__":
    raise SystemExit(main())
