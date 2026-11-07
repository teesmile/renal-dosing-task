#!/usr/bin/env python3
"""Compare solution/solve.py, the independent SQLite implementation and the
frozen ground truth, patient by patient. Also confirms the ground truth was
built from the current environment files (SHA-256 match).

Writes authoring/evidence/results/independent_agreement.json; exits non-zero
on any disagreement.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV = ROOT / "environment"
HERE = Path(__file__).resolve().parent


def run(script: Path, out: Path) -> dict[str, dict]:
    subprocess.run([sys.executable, str(script), str(ENV), str(out)], check=True)
    return {r["patient_id"]: r for r in map(json.loads, out.read_text().splitlines())}


def main() -> int:
    gt_doc = json.loads((ROOT / "tests" / "ground_truth.json").read_text())
    gt = gt_doc["patients"]
    problems = []
    for name, digest in gt_doc["input_sha256"].items():
        if hashlib.sha256((ENV / name).read_bytes()).hexdigest() != digest:
            problems.append(f"ground truth is stale: {name} changed since it was built")

    with tempfile.TemporaryDirectory() as tmp:
        ref = run(ROOT / "solution" / "solve.py", Path(tmp) / "ref.jsonl")
        ind = run(HERE / "independent_sqlite.py", Path(tmp) / "ind.jsonl")

    rows = []
    for pid in sorted(set(gt) | set(ref) | set(ind)):
        g, r, i = gt.get(pid), ref.get(pid), ind.get(pid)
        if not (g and r and i):
            problems.append(f"{pid} missing from one source")
            continue
        crcl_agree = g["crcl_ml_min"] == r["crcl_ml_min"] == i["crcl_ml_min"]
        flags_agree = set(g["flagged_order_ids"]) == set(r["flagged_order_ids"]) == set(i["flagged_order_ids"])
        if not (crcl_agree and flags_agree):
            problems.append(f"{pid}: gt={g} ref={r} independent={i}")
        rows.append({"patient_id": pid, "crcl_ml_min": {"ground_truth": g["crcl_ml_min"], "solve_py":
                     r["crcl_ml_min"], "independent_sqlite": i["crcl_ml_min"]},
                     "flagged_order_ids": {"ground_truth": g["flagged_order_ids"], "solve_py": r["flagged_order_ids"],
                                           "independent_sqlite": sorted(i["flagged_order_ids"])},
                     "agree": crcl_agree and flags_agree})

    report = {"compared": ["tests/ground_truth.json", "solution/solve.py", "authoring/evidence/independent_sqlite.py"],
              "rule": "CrCl identical at 0.1 mL/min and flagged sets identical",
              "patients": rows, "all_agree": not problems, "problems": problems}
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / "independent_agreement.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"{sum(r['agree'] for r in rows)}/{len(rows)} patients agree across ground truth, solve.py and SQLite")
    for p in problems:
        print("PROBLEM:", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
