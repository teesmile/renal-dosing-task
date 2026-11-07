# Renal dose check

> **Fictional data.** Every patient is synthetic, and the drugs and dose limits in
> `rules.json` were invented for this exercise. They are not clinical guidance.

A ward chart has been exported to `/app`:

- `patients.csv`: `patient_id, age_years, sex, weight, weight_unit`
- `labs.csv`: serum creatinine results, `patient_id, creatinine, creatinine_unit, collected_at`
- `meds.csv`: medication orders, `order_id, patient_id, drug, dose_mg, frequency, start_time, status`
- `rules.json`: renal dosing rules for each drug, given as creatinine-clearance bands and the maximum daily dose allowed in each band

The chart uses mixed units. Check every patient against `rules.json`. Use only those rules, not outside dosing knowledge.

## What to compute

1. **Creatinine clearance (CrCl)** in mL/min, using the Cockcroft–Gault equation with **actual body weight** and the patient's **most recent** creatinine (latest `collected_at`):

   `CrCl = (140 − age_years) × weight_kg / (72 × SCr_mg/dL)`, multiplied by 0.85 if `sex` is `F`.

   Unit conversions: 1 lb = 0.45359237 kg, and SCr in mg/dL = SCr in µmol/L ÷ 88.4.

2. **Daily dose** of each order = `dose_mg` × administrations per day. Frequencies use standard prescribing notation: `OD` and `daily` mean once daily, `BD` twice, `TDS` three times and `QDS` four times a day, and `qNh` means every N hours.

3. **Band**: a drug's band applies when `crcl_min ≤ CrCl < crcl_max`. A `null` bound is unbounded. Choose the band using the unrounded CrCl.

4. **Flag** an order when it is `active` and its daily dose is **strictly greater** than `max_daily_dose_mg` for the patient's band. Never flag orders that are not active.

## Output

Write `/app/output/dose_check.jsonl` with exactly one JSON object per line and one line per patient in `patients.csv`:

```json
{"patient_id": "PT001", "crcl_ml_min": 87.3, "flagged_order_ids": ["RX1234"]}
```

- `crcl_ml_min`: a number rounded to 0.1 mL/min.
- `flagged_order_ids`: a list of `order_id` strings, empty if nothing is flagged. Order does not matter.
