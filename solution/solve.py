#!/usr/bin/env python3
"""Reference solution: renal dose check (fictional drugs, synthetic patients).

Reads patients.csv, labs.csv, meds.csv and rules.json from DATA_DIR and writes
one JSON line per patient to OUT_PATH.

    python3 solve.py [DATA_DIR] [OUT_PATH]

Defaults: DATA_DIR=/app, OUT_PATH=/app/output/dose_check.jsonl
"""
from __future__ import annotations

import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path

LB_TO_KG = 0.45359237
UMOL_PER_MGDL = 88.4

NAMED_FREQUENCIES = {"OD": 1, "DAILY": 1, "BD": 2, "TDS": 3, "QDS": 4}
EVERY_N_HOURS = re.compile(r"^Q(\d+)H$")


def doses_per_day(freq: str) -> float:
    f = freq.strip().upper()
    if f in NAMED_FREQUENCIES:
        return NAMED_FREQUENCIES[f]
    m = EVERY_N_HOURS.match(f)
    if m:
        hours = int(m.group(1))
        if hours <= 0 or 24 % hours:
            raise ValueError(f"interval does not divide a day: {freq!r}")
        return 24 // hours
    raise ValueError(f"unknown frequency: {freq!r}")


def weight_kg(value: float, unit: str) -> float:
    u = unit.strip().lower()
    if u == "kg":
        return value
    if u in ("lb", "lbs"):
        return value * LB_TO_KG
    raise ValueError(f"unknown weight unit: {unit!r}")


def creatinine_mg_dl(value: float, unit: str) -> float:
    u = unit.strip().lower().replace("μ", "µ")
    if u == "mg/dl":
        return value
    if u in ("µmol/l", "umol/l"):
        return value / UMOL_PER_MGDL
    raise ValueError(f"unknown creatinine unit: {unit!r}")


def cockcroft_gault(age: float, sex: str, wt_kg: float, scr_mg_dl: float) -> float:
    crcl = (140 - age) * wt_kg / (72 * scr_mg_dl)
    if sex.strip().upper() == "F":
        crcl *= 0.85
    return crcl


def band_limit(bands: list[dict], crcl: float) -> float:
    for b in bands:
        lo, hi = b["crcl_min"], b["crcl_max"]
        if (lo is None or crcl >= lo) and (hi is None or crcl < hi):
            return b["max_daily_dose_mg"]
    raise ValueError(f"no band covers CrCl {crcl}")


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main(data_dir: Path, out_path: Path) -> None:
    rules = json.loads((data_dir / "rules.json").read_text(encoding="utf-8"))["drugs"]
    patients = read_csv(data_dir / "patients.csv")

    latest: dict[str, tuple[datetime, float]] = {}
    for row in read_csv(data_dir / "labs.csv"):
        t = datetime.fromisoformat(row["collected_at"])
        scr = creatinine_mg_dl(float(row["creatinine"]), row["creatinine_unit"])
        pid = row["patient_id"]
        if pid not in latest or t > latest[pid][0]:
            latest[pid] = (t, scr)

    orders: dict[str, list[dict]] = {}
    for row in read_csv(data_dir / "meds.csv"):
        orders.setdefault(row["patient_id"], []).append(row)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as out:
        for p in patients:
            pid = p["patient_id"]
            wt = weight_kg(float(p["weight"]), p["weight_unit"])
            crcl = cockcroft_gault(float(p["age_years"]), p["sex"], wt, latest[pid][1])
            flagged = []
            for o in orders.get(pid, []):
                if o["status"].strip().lower() != "active":
                    continue
                daily = float(o["dose_mg"]) * doses_per_day(o["frequency"])
                if daily > band_limit(rules[o["drug"]], crcl):
                    flagged.append(o["order_id"])
            out.write(json.dumps({
                "patient_id": pid,
                "crcl_ml_min": round(crcl, 1),
                "flagged_order_ids": sorted(flagged),
            }) + "\n")


if __name__ == "__main__":
    args = sys.argv[1:]
    main(Path(args[0]) if args else Path("/app"),
         Path(args[1]) if len(args) > 1 else Path("/app/output/dose_check.jsonl"))
