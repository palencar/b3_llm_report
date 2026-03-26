import argparse
import os
import sys

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from b3_core.config import load_config
from b3_etl.cvm import run_ingest_cvm


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingestão bulk CVM (DFP/ITR) para dados fundamentalistas."
    )
    parser.add_argument(
        "--year",
        type=int,
        required=True,
        help="Ano de referência (ex: 2024).",
    )
    parser.add_argument(
        "--itr",
        action="store_true",
        help="Incluir ITR trimestral além do DFP anual.",
    )
    parser.add_argument(
        "--skip-db",
        action="store_true",
        help="Não gravar no DuckDB (mantém apenas raw files).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    config = load_config()
    return run_ingest_cvm(
        year=args.year,
        include_itr=args.itr,
        config=config,
        skip_db=args.skip_db,
    )


if __name__ == "__main__":
    raise SystemExit(main())
