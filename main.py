import argparse
import os
import sys


ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from b3_report.cli import run_report  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Script para processar simbolos de negociacao.")
    parser.add_argument("symbol", type=str, help="Simbolo de negociacao (exemplo: PETR4, VALE3)")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    symbol = args.symbol.upper()
    print(f"Processando simbolo: {symbol}")
    analysis = run_report(symbol)
    print(analysis)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
