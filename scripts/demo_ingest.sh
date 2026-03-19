#!/usr/bin/env bash
set -euo pipefail

if [ $# -eq 0 ]; then
  echo "Uso: bash scripts/demo_ingest.sh PETR4,ITUB4,VALE3"
  exit 1
fi

python ingest.py --tickers "$1"
