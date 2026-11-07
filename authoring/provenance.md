# Provenance

## Origin

Everything in this task was written from scratch for this repository. No data,
code, wording or ground truth comes from another benchmark task or from a real
patient record.

- **Patients.** The 15 adults are synthetic. Ages, sexes, weights, creatinine
  values and orders were chosen by hand in `authoring/generate_data.py`
  (`PATIENTS`) so that each patient exercises at most one trap.
- **Drugs and limits.** The names Aldrovexin, Bremazotan, Cylvarone, Dorvatinex
  and Exalmizide, and every clearance band and dose limit in `rules.json`, are
  invented. They are not intended to resemble any real product, and they are
  **not clinical guidance**.
- **Randomness.** `random.Random(20261107)` produces only the order ids, the
  timestamps and the row order of `labs.csv` and `meds.csv`. Re-running the
  generator reproduces `environment/` byte for byte.
- **Formula and constants.** Cockcroft–Gault, with the 0.85 factor for female
  patients, 88.4 µmol/L per mg/dL and 0.45359237 kg/lb. These are standard
  textbook constants, and the instruction states them explicitly.

## Build chain

```
authoring/generate_data.py      -> environment/{patients,labs,meds}.csv, rules.json
                                   authoring/patient_design.json (trap family per patient)
authoring/build_ground_truth.py -> runs solution/solve.py -> tests/ground_truth.json
                                   (records SHA-256 of every environment input)
authoring/evidence/run_all.sh   -> all of the above, then both evidence checks
```

Input hashes recorded in `tests/ground_truth.json` at the time of commit:

| file | sha256 |
|---|---|
| patients.csv | `d4103aa0058601ea98ffcae15bc9b453e6073d513ce844b2af842fb761dbcfe2` |
| labs.csv | `1a4ba09bf59b0898f85a3a6c9f11f61d687caf5a1b8eb679eda5b003bc1c6c14` |
| meds.csv | `ddfcc3406fe1794dd086339883ec7f49493ecf936f832e2e95e4e7a6c8e45bac` |
| rules.json | `a5e71609331c5a9a0756ca39f02f7d536f514feed561afe735bbae216c18e58b` |

`authoring/evidence/check_independent.py` recomputes these hashes and fails if
the ground truth is stale.

## Patient design

| patient | trap family | role | reference CrCl | flagged |
|---|---|---|---|---|
| PT001 | creatinine_unit | µmol/L creatinine (88) | 98.4 | RX8233 |
| PT002 | creatinine_unit | **trap**: µmol/L (150) read as mg/dL | 32.5 | RX1560 |
| PT003 | creatinine_unit | µmol/L (97); misreading flags two orders that are fine | 109.4 | — |
| PT004 | creatinine_unit | **look-alike**: 16 µmol/L in a frail 38 kg 90-year-old | 123.9 | — |
| PT005 | weight_unit | **trap**: 176 lb read as kg | 47.1 | RX6102 |
| PT006 | weight_unit | 231 lb | 78.0 | RX2058 |
| PT007 | weight_unit | **look-alike**: genuine 150 kg | 152.2 | — |
| PT008 | order_status | **trap**: discontinued over-limit order | 64.0 | — |
| PT009 | frequency | **trap**: q8h (= 3/day), plus q12h | 78.2 | — |
| PT010 | frequency | **trap**: BD (= 2/day) | 27.0 | RX5724 |
| PT011 | frequency | **trap**: TDS (= 3/day) | 99.3 | RX7981 |
| PT012 | latest_lab | older AKI creatinine listed after the newer one | 100.0 | — |
| PT013 | limit_boundary | daily dose exactly equal to the limit (not flagged) | 55.1 | RX4803 |
| PT014 | weight_unit | 209 lb, low clearance band | 23.0 | RX4887 |
| PT015 | control | no trap | 11.4 | RX8323 |

"Trap family" names the only class of mistake that can change this patient's
answer. `simulate_agents.py` checks this empirically rather than taking it on
trust (see `evidence/results/simulation_results.md`, "Trap isolation").

## Tooling used

Authored on Linux with Python 3.14 (standard library only), with pytest 8.3.3
pinned through `uv`. The container image is `python:3.12-slim-bookworm`. The
solution and both evidence implementations use only the standard library.
