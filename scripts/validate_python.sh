#!/usr/bin/env bash
set -euo pipefail

python -m py_compile \
  relatorio \
  main.py \
  watch_queue.py \
  init_db.py \
  ingest.py \
  get_info_yfinance.py \
  src/b3_core/config.py \
  src/b3_core/log.py \
  src/b3_storage/db.py \
  src/b3_storage/schema.py \
  src/b3_storage/fundamentus.py \
  src/b3_etl/brapi.py \
  src/b3_etl/ingest.py \
  src/b3_report/llm.py \
  src/b3_report/reports.py \
  src/b3_report/queue_control.py \
  src/b3_report/token_usage.py \
  src/b3_report/assessment.py \
  src/b3_report/decision_snapshot.py \
  src/b3_report/model_state.py \
  src/b3_report/events.py \
  src/b3_report/aligned_pipeline.py \
  src/b3_report/rubric.py \
  src/b3_report/textual_baseline.py \
  src/b3_report/unified.py \
  src/b3_report/sources/yfinance.py \
  src/b3_report/sources/fundamentus.py
