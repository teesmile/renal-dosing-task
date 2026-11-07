#!/usr/bin/env python3
"""Generate the synthetic chart for the renal dose-check task.

Everything here is invented. The five drugs, their clearance bands and their
dose limits are fictional and must not be read as clinical guidance.

Clinical values (age, sex, weight, creatinine, doses, frequencies) are designed
by hand so that each patient carries at most one trap (see PATIENTS[*]["family"]).
The seeded RNG only controls identifiers, timestamps and the row order of the
CSV files, so re-running this script reproduces the environment byte for byte.

Usage:  python3 authoring/generate_data.py
"""
from __future__ import annotations

import csv
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

SEED = 20261107
ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / "environment"

# --------------------------------------------------------------------------
# Fictional rules. Bands are half-open: crcl_min <= CrCl < crcl_max, with
# null meaning unbounded. max_daily_dose_mg = 0 means "do not use in band".
# --------------------------------------------------------------------------
RULES = {
    "_notice": (
        "FICTIONAL. These drugs and limits were invented for a software benchmark. "
        "They are not real medicines and this is not clinical guidance."
    ),
    "band_semantics": "crcl_min <= CrCl_mL_min < crcl_max; null bound = unbounded",
    "dose_unit": "mg/day",
    "drugs": {
        "Aldrovexin": [
            {"crcl_min": 60, "crcl_max": None, "max_daily_dose_mg": 3000},
            {"crcl_min": 30, "crcl_max": 60, "max_daily_dose_mg": 1500},
            {"crcl_min": 15, "crcl_max": 30, "max_daily_dose_mg": 750},
            {"crcl_min": None, "crcl_max": 15, "max_daily_dose_mg": 0},
        ],
        "Bremazotan": [
            {"crcl_min": 50, "crcl_max": None, "max_daily_dose_mg": 400},
            {"crcl_min": 25, "crcl_max": 50, "max_daily_dose_mg": 200},
            {"crcl_min": None, "crcl_max": 25, "max_daily_dose_mg": 100},
        ],
        "Cylvarone": [
            {"crcl_min": 90, "crcl_max": None, "max_daily_dose_mg": 1200},
            {"crcl_min": 45, "crcl_max": 90, "max_daily_dose_mg": 900},
            {"crcl_min": 20, "crcl_max": 45, "max_daily_dose_mg": 450},
            {"crcl_min": None, "crcl_max": 20, "max_daily_dose_mg": 0},
        ],
        "Dorvatinex": [
            {"crcl_min": 40, "crcl_max": None, "max_daily_dose_mg": 60},
            {"crcl_min": 10, "crcl_max": 40, "max_daily_dose_mg": 30},
            {"crcl_min": None, "crcl_max": 10, "max_daily_dose_mg": 0},
        ],
        "Exalmizide": [
            {"crcl_min": 70, "crcl_max": None, "max_daily_dose_mg": 2000},
            {"crcl_min": 35, "crcl_max": 70, "max_daily_dose_mg": 1000},
            {"crcl_min": None, "crcl_max": 35, "max_daily_dose_mg": 500},
        ],
    },
}

UMOL = "µmol/L"
MGDL = "mg/dL"

# --------------------------------------------------------------------------
# Patient designs. `labs` entries: (value, unit, days_before_index).
# `orders` entries: (drug, dose_mg, frequency, status).
# `family` names the single trap family the patient is sensitive to.
# `note` is authoring documentation only; it never reaches the environment.
# --------------------------------------------------------------------------
PATIENTS = [
    dict(age=54, sex="M", weight=82, wunit="kg", labs=[(88, UMOL, 2)],
         orders=[("Aldrovexin", 1000, "OD", "active"), ("Exalmizide", 2500, "daily", "active")],
         family="creatinine_unit", note="µmol/L creatinine; Exalmizide over limit at any sane CrCl"),
    dict(age=67, sex="F", weight=64, wunit="kg", labs=[(150, UMOL, 1)],
         orders=[("Bremazotan", 300, "OD", "active"), ("Cylvarone", 400, "OD", "active")],
         family="creatinine_unit", note="TRAP µmol/L read as mg/dL drops CrCl to ~0.4 and flags Cylvarone"),
    dict(age=45, sex="M", weight=91, wunit="kg", labs=[(97, UMOL, 3)],
         orders=[("Dorvatinex", 40, "OD", "active"), ("Aldrovexin", 2000, "OD", "active")],
         family="creatinine_unit", note="µmol/L; misread flags both orders that are actually fine"),
    dict(age=90, sex="F", weight=38, wunit="kg", labs=[(16, UMOL, 1)],
         orders=[("Cylvarone", 250, "QDS", "active"), ("Exalmizide", 1000, "OD", "active")],
         family="creatinine_unit",
         note="LOOK-ALIKE: 16 µmol/L (frail, sarcopenic) looks like an ESRD mg/dL value"),
    dict(age=72, sex="M", weight=176, wunit="lb", labs=[(1.6, MGDL, 2)],
         orders=[("Bremazotan", 300, "OD", "active")],
         family="weight_unit", note="TRAP lb read as kg lifts CrCl past 50 and hides the flag"),
    dict(age=58, sex="F", weight=231, wunit="lb", labs=[(1.3, MGDL, 1)],
         orders=[("Cylvarone", 1000, "OD", "active"), ("Exalmizide", 1500, "OD", "active")],
         family="weight_unit", note="lb; misread lifts CrCl past 90 and hides the Cylvarone flag"),
    dict(age=45, sex="M", weight=150, wunit="kg", labs=[(1.3, MGDL, 2)],
         orders=[("Aldrovexin", 2500, "OD", "active"), ("Dorvatinex", 50, "OD", "active"),
                 ("Cylvarone", 1000, "OD", "active")],
         family="weight_unit",
         note="LOOK-ALIKE: genuine 150 kg; a 'big number must be lb' rule flags Cylvarone"),
    dict(age=61, sex="M", weight=70, wunit="kg", labs=[(1.2, MGDL, 1)],
         orders=[("Aldrovexin", 3500, "OD", "discontinued"), ("Aldrovexin", 2000, "OD", "active"),
                 ("Bremazotan", 200, "OD", "active")],
         family="order_status", note="TRAP discontinued 3500 mg order exceeds limit; active ones do not"),
    dict(age=39, sex="F", weight=59, wunit="kg", labs=[(0.9, MGDL, 2)],
         orders=[("Exalmizide", 600, "q8h", "active"), ("Cylvarone", 200, "q12h", "active")],
         family="frequency", note="TRAP q8h = 3/day (not 8); q12h = 2/day"),
    dict(age=80, sex="M", weight=68, wunit="kg", labs=[(2.1, MGDL, 1)],
         orders=[("Aldrovexin", 500, "BD", "active"), ("Bremazotan", 100, "OD", "active")],
         family="frequency", note="TRAP BD = 2/day -> 1000 mg > 750"),
    dict(age=33, sex="F", weight=55, wunit="kg", labs=[(0.7, MGDL, 2)],
         orders=[("Cylvarone", 450, "TDS", "active"), ("Dorvatinex", 15, "TDS", "active")],
         family="frequency", note="TRAP TDS = 3/day -> 1350 mg > 1200"),
    dict(age=50, sex="M", weight=88, wunit="kg", labs=[(1.1, MGDL, 1), (2.6, MGDL, 10)],
         orders=[("Cylvarone", 1100, "OD", "active"), ("Bremazotan", 300, "OD", "active")],
         family="latest_lab",
         note="TRAP older AKI creatinine 2.6 is listed after the recovered 1.1 in labs.csv"),
    dict(age=70, sex="F", weight=60, wunit="kg", labs=[(0.9, MGDL, 2)],
         orders=[("Exalmizide", 250, "QDS", "active"), ("Bremazotan", 500, "OD", "active")],
         family="limit_boundary", note="TRAP Exalmizide 1000 mg/day equals the 1000 limit: not exceeding"),
    dict(age=77, sex="M", weight=209, wunit="lb", labs=[(3.6, MGDL, 1)],
         orders=[("Dorvatinex", 40, "OD", "active"), ("Aldrovexin", 600, "OD", "active"),
                 ("Cylvarone", 400, "OD", "active")],
         family="weight_unit", note="lb; low CrCl band"),
    dict(age=85, sex="F", weight=49, wunit="kg", labs=[(2.8, MGDL, 3)],
         orders=[("Bremazotan", 75, "OD", "active"), ("Dorvatinex", 20, "OD", "active"),
                 ("Exalmizide", 600, "OD", "active")],
         family="control", note="no trap; CrCl ~11"),
]

DESIGN_PATH = Path(__file__).resolve().parent / "patient_design.json"


def main() -> None:
    rng = random.Random(SEED)
    index_time = datetime(2026, 11, 2, 8, 0)
    order_ids = rng.sample(range(1000, 9999), sum(len(p["orders"]) for p in PATIENTS))

    patients_rows, lab_rows, med_rows, design = [], [], [], []
    oi = 0
    for n, p in enumerate(PATIENTS, start=1):
        pid = f"PT{n:03d}"
        patients_rows.append([pid, p["age"], p["sex"], p["weight"], p["wunit"]])
        for value, unit, days in p["labs"]:
            t = index_time - timedelta(days=days, minutes=rng.randrange(0, 600))
            lab_rows.append([pid, value, unit, t.strftime("%Y-%m-%dT%H:%M")])
        ids = []
        for drug, dose, freq, status in p["orders"]:
            oid = f"RX{order_ids[oi]}"
            oi += 1
            ids.append(oid)
            start = index_time - timedelta(days=rng.randrange(1, 20), minutes=rng.randrange(0, 1440))
            med_rows.append([oid, pid, drug, dose, freq, start.strftime("%Y-%m-%dT%H:%M"), status])
        design.append({"patient_id": pid, "family": p["family"], "note": p["note"], "order_ids": ids})

    # Shuffle labs/meds so nothing can be inferred from row order, except that the
    # latest_lab patient keeps "newest row first" to defeat last-row-wins parsing.
    rng.shuffle(lab_rows)
    rng.shuffle(med_rows)
    for p_idx, p in enumerate(PATIENTS, start=1):
        if p["family"] == "latest_lab":
            pid = f"PT{p_idx:03d}"
            mine = sorted([r for r in lab_rows if r[0] == pid], key=lambda r: r[3], reverse=True)
            slots = [i for i, r in enumerate(lab_rows) if r[0] == pid]
            for slot, row in zip(slots, mine):
                lab_rows[slot] = row

    ENV.mkdir(parents=True, exist_ok=True)
    write_csv(ENV / "patients.csv", ["patient_id", "age_years", "sex", "weight", "weight_unit"], patients_rows)
    write_csv(ENV / "labs.csv", ["patient_id", "creatinine", "creatinine_unit", "collected_at"], lab_rows)
    write_csv(ENV / "meds.csv", ["order_id", "patient_id", "drug", "dose_mg", "frequency", "start_time", "status"],
              med_rows)
    (ENV / "rules.json").write_text(json.dumps(RULES, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    DESIGN_PATH.write_text(json.dumps(design, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(patients_rows)} patients, {len(lab_rows)} labs, {len(med_rows)} orders (seed {SEED})")


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


if __name__ == "__main__":
    main()
