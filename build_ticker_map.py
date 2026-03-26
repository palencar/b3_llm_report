import argparse
import os
import sys

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from b3_core.config import load_config
from b3_etl.ticker_map import run_build_ticker_map


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Constrói mapeamento CNPJ→ticker via API da B3."
    )
    parser.add_argument(
        "--skip-db",
        action="store_true",
        help="Não gravar no DuckDB (apenas parseia e loga).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    config = load_config()
    return run_build_ticker_map(config=config, skip_db=args.skip_db)


if __name__ == "__main__":
    raise SystemExit(main())
