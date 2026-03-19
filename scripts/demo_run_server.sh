#!/usr/bin/env bash
set -euo pipefail

uvicorn mcp_server:app --host 0.0.0.0 --port "${PORT:-8000}"
