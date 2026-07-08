#!/bin/bash
# Resume tầng ĐẮT skywalking với 4 worker (nâng từ 3) rồi nối relabel->kappa->export.
# Scan (①) đã xong, select (②) đã đầy hàng đợi -> chỉ cần drain analyze + hậu xử lý.
set -uo pipefail
cd /home/scanner/tool-scan-commit
export ORCH_SQLITE=data/dataset_skywalking.sqlite
export ORCH_EXPENSIVE_WORKERS=4
export PYTHONPATH=src
REPO=https://github.com/apache/skywalking

echo "===== RESUME @ $(date -u +%FT%TZ) | analyze 4 worker (nâng từ 3) ====="
python3 -m orchestrator.cli analyze "$REPO" --workers 4 --codeql 0
echo "===== ANALYZE xong @ $(date -u +%FT%TZ) -> RELABEL ====="
python3 -m orchestrator.cli relabel "$REPO"
echo "===== RELABEL xong -> KAPPA ====="
python3 -m orchestrator.cli kappa
echo "===== KAPPA xong -> EXPORT ====="
python3 -m orchestrator.cli export --out data/export_skywalking
echo "===== PIPELINE HOÀN TẤT @ $(date -u +%FT%TZ) ====="
