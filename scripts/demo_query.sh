#!/usr/bin/env bash
set -euo pipefail

if [ $# -eq 0 ]; then
  echo "Uso: bash scripts/demo_query.sh PETR4"
  exit 1
fi

if [ -z "${AUTH_TOKEN:-}" ]; then
  echo "Defina AUTH_TOKEN antes de consultar o MCP."
  exit 1
fi

curl \
  -H "Authorization: Bearer ${AUTH_TOKEN}" \
  "http://localhost:${PORT:-8000}/v1/fundamentals/$1"
