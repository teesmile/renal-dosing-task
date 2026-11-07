#!/usr/bin/env bash
# Oracle entry point: runs the reference solution against the chart in /app.
set -euo pipefail
python3 "$(dirname "$0")/solve.py" /app /app/output/dose_check.jsonl
