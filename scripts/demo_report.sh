#!/usr/bin/env bash
set -euo pipefail

if [ $# -eq 0 ]; then
  echo "Uso: bash scripts/demo_report.sh PETR4"
  exit 1
fi

python main.py "$1"
