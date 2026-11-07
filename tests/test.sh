#!/usr/bin/env bash
# Verifier entry point: runs inside the task container with tests/ mounted at /tests.
set -uo pipefail

pip install --quiet --no-cache-dir pytest==8.3.3

mkdir -p /logs/verifier
if python -m pytest -q -p no:cacheprovider /tests/test_outputs.py; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
