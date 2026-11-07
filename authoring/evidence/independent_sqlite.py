#!/usr/bin/env python3
"""Independent implementation of the dose check, written against the task
instruction only (no code shared with solution/solve.py).

Where solve.py is procedural Python, this loads the chart into an in-memory
SQLite database and does unit conversion, latest-lab selection, Cockcroft-Gault,
frequency expansion and band lookup in SQL. Frequencies are resolved through an
explicit lookup table rather than a regex, and the band join uses SQL NULL
semantics instead of Python comparisons.

    python3 independent_sqlite.py DATA_DIR OUT_PATH
"""
from __future__ import annotations

import csv
import json
import sqlite3
import sys
from pathlib import Path

FREQ_TABLE = [  # (normalised frequency, administrations per day)
    ("OD", 1), ("DAILY", 1), ("BD", 2), ("TDS", 3), ("QDS", 4),
    ("Q24H", 1), ("Q12H", 2), ("Q8H", 3), ("Q6H", 4), ("Q4H", 6),
]

CTES = """
WITH latest AS (
    SELECT l.patient_id,
           CASE l.creatinine_unit WHEN 'mg/dL' THEN l.creatinine
                                  WHEN 'µmol/L' THEN l.creatinine / 88.4 END AS scr_mgdl
    FROM labs l
    WHERE l.collected_at = (SELECT MAX(collected_at) FROM labs x WHERE x.patient_id = l.patient_id)
),
crcl AS (
    SELECT p.patient_id,
           (140.0 - p.age_years)
             * CASE p.weight_unit WHEN 'kg' THEN p.weight WHEN 'lb' THEN p.weight * 0.45359237 END
             / (72.0 * lt.scr_mgdl)
             * CASE p.sex WHEN 'F' THEN 0.85 ELSE 1.0 END AS crcl
    FROM patients p JOIN latest lt USING (patient_id)
),
daily AS (
    SELECT m.order_id, m.patient_id, m.drug, m.dose_mg * f.per_day AS daily_mg
    FROM meds m JOIN freq f ON f.code = UPPER(TRIM(m.frequency))
    WHERE m.status = 'active'
),
limited AS (
    SELECT d.order_id, d.patient_id, d.daily_mg, b.max_mg
    FROM daily d
    JOIN crcl c USING (patient_id)
    LEFT JOIN bands b ON b.drug = d.drug
                     AND (b.lo IS NULL OR c.crcl >= b.lo)
                     AND (b.hi IS NULL OR c.crcl < b.hi)
)
"""
CRCL_SQL = CTES + "SELECT patient_id, crcl FROM crcl ORDER BY patient_id"
UNBANDED_SQL = CTES + "SELECT order_id FROM limited WHERE max_mg IS NULL"
FLAG_SQL = CTES + "SELECT patient_id, order_id FROM limited WHERE daily_mg > max_mg ORDER BY order_id"


def main(data_dir: Path, out_path: Path) -> None:
    db = sqlite3.connect(":memory:")
    for name, cols in [("patients", "patient_id TEXT, age_years REAL, sex TEXT, weight REAL, weight_unit TEXT"),
                       ("labs", "patient_id TEXT, creatinine REAL, creatinine_unit TEXT, collected_at TEXT"),
                       ("meds", "order_id TEXT, patient_id TEXT, drug TEXT, dose_mg REAL, frequency TEXT, "
                                "start_time TEXT, status TEXT")]:
        db.execute(f"CREATE TABLE {name} ({cols})")
        with (data_dir / f"{name}.csv").open(newline="", encoding="utf-8") as fh:
            rows = list(csv.reader(fh))[1:]
        db.executemany(f"INSERT INTO {name} VALUES ({','.join('?' * len(rows[0]))})", rows)

    # Unknown units/frequencies must surface, not silently vanish in a join.
    bad = db.execute("SELECT DISTINCT creatinine_unit FROM labs WHERE creatinine_unit NOT IN ('mg/dL','µmol/L') "
                     "UNION SELECT DISTINCT weight_unit FROM patients WHERE weight_unit NOT IN ('kg','lb')").fetchall()
    assert not bad, f"unexpected units {bad}"
    db.execute("CREATE TABLE freq (code TEXT PRIMARY KEY, per_day INTEGER)")
    db.executemany("INSERT INTO freq VALUES (?, ?)", FREQ_TABLE)
    unknown = db.execute("SELECT DISTINCT frequency FROM meds WHERE UPPER(TRIM(frequency)) NOT IN "
                         "(SELECT code FROM freq)").fetchall()
    assert not unknown, f"unexpected frequencies {unknown}"
    ties = db.execute("SELECT patient_id FROM labs GROUP BY patient_id, collected_at HAVING COUNT(*) > 1").fetchall()
    assert not ties, f"tied latest labs {ties}"

    db.execute("CREATE TABLE bands (drug TEXT, lo REAL, hi REAL, max_mg REAL)")
    rules = json.loads((data_dir / "rules.json").read_text(encoding="utf-8"))["drugs"]
    db.executemany("INSERT INTO bands VALUES (?, ?, ?, ?)",
                   [(d, b["crcl_min"], b["crcl_max"], b["max_daily_dose_mg"]) for d, bs in rules.items() for b in bs])

    unbanded = db.execute(UNBANDED_SQL).fetchall()
    assert not unbanded, f"orders with no matching band {unbanded}"
    result = {pid: {"patient_id": pid, "crcl_ml_min": round(c, 1), "flagged_order_ids": []}
              for pid, c in db.execute(CRCL_SQL)}
    assert len(result) == db.execute("SELECT COUNT(*) FROM patients").fetchone()[0], "patient without a lab"
    for pid, oid in db.execute(FLAG_SQL):
        result[pid]["flagged_order_ids"].append(oid)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(json.dumps(result[k]) + "\n" for k in sorted(result)), encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
