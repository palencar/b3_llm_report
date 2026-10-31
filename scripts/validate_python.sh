#!/usr/bin/env bash
set -euo pipefail

python -m py_compile \
  main.py \
  init_db.py \
  ingest.py \
  get_info_yfinance.py \
  src/b3_core/config.py \
  src/b3_core/log.py \
  src/b3_storage/db.py \
  src/b3_storage/schema.py \
  src/b3_etl/brapi.py \
  src/b3_etl/ingest.py \
  src/b3_report/cli.py \
  src/b3_report/llm.py \
  src/b3_report/prompts.py \
  src/b3_report/sources/yfinance.py \
  src/b3_report/sources/fundamentus.py
