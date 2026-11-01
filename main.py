import argparse
import os
import sys


ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from b3_report.aligned_pipeline import run_aligned  # noqa: E402
from b3_report.textual_baseline import format_report_markdown  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Script para processar simbolos de negociacao.")
    parser.add_argument("symbol", type=str, help="Simbolo de negociacao (exemplo: PETR4, VALE3)")
    parser.add_argument("--snapshot", "--decision-snapshot", dest="snapshot",
                        help="Reutiliza um snapshot JSON sem coletar fontes novamente.")
    parser.add_argument("--unified", action="store_true",
                        help="Alias de compatibilidade; o relatorio unificado e o unico fluxo.")
    parser.add_argument("--structured-output", choices=("on", "off"), default="off",
                        help="Solicita JSON Schema na API de chat; padrao off, sem fallback automatico.")
    args = parser.parse_args()
    return args


def main() -> int:
    args = _parse_args()
    symbol = args.symbol.upper()
    structured = {"structured_output": True} if args.structured_output == "on" else {}
    print(f"Processando simbolo: {symbol}")
    outcome = run_aligned(symbol, snapshot_path=args.snapshot, **structured)
    if "unified" in outcome["results"]:
        print(format_report_markdown(outcome["results"]["unified"]))
    return 1 if outcome["failed_modes"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
