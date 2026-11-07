#!/usr/bin/env bash
# Rebuild the task from its seed and regenerate all evidence.
# Requires python3 and uv (for a pinned pytest). Exits non-zero on any failure.
set -euo pipefail
cd "$(dirname "$0")/../.."

PY=(uv run --no-project --with pytest==8.3.3 python)

"${PY[@]}" authoring/generate_data.py
"${PY[@]}" authoring/build_ground_truth.py
git diff --exit-code --stat -- environment tests/ground_truth.json \
  || echo "note: regenerated data differs from the committed copy (expected only while authoring)"
"${PY[@]}" authoring/evidence/check_independent.py
"${PY[@]}" authoring/evidence/simulate_agents.py
