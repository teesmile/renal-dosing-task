#!/usr/bin/env python3
"""Run solution/solve.py on environment/ and freeze its answer as tests/ground_truth.json.

The SHA-256 of every environment input is recorded so evidence scripts can
detect a ground truth that has drifted from the data it was built from.
Independence is checked separately by authoring/evidence/independent_sqlite.py.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INPUTS = ["patients.csv", "labs.csv", "meds.csv", "rules.json"]


def input_hashes() -> dict[str, str]:
    return {n: hashlib.sha256((ROOT / "environment" / n).read_bytes()).hexdigest() for n in INPUTS}


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "dose_check.jsonl"
        subprocess.run([sys.executable, str(ROOT / "solution" / "solve.py"), str(ROOT / "environment"), str(out)],
                       check=True)
        rows = [json.loads(line) for line in out.read_text().splitlines() if line.strip()]
    gt = {
        "_notice": "Fictional drugs and limits; not clinical guidance.",
        "source": "solution/solve.py run on environment/ by authoring/build_ground_truth.py",
        "input_sha256": input_hashes(),
        "crcl_rel_tolerance": 0.01,
        "patients": {r["patient_id"]: {"crcl_ml_min": r["crcl_ml_min"],
                                       "flagged_order_ids": sorted(r["flagged_order_ids"])} for r in rows},
    }
    (ROOT / "tests" / "ground_truth.json").write_text(json.dumps(gt, indent=2) + "\n")
    print(f"ground truth: {len(rows)} patients")


if __name__ == "__main__":
    main()
