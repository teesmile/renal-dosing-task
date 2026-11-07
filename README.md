# Renal dose check: a sample AI-agent benchmark task

> ⚠️ **The drugs and dose limits in this repository are fictional.**
> Aldrovexin, Bremazotan, Cylvarone, Dorvatinex and Exalmizide are invented
> names, and every clearance band and maximum dose in `environment/rules.json`
> was made up for this benchmark. **Nothing here is clinical guidance.** Do not
> use it to dose a real patient. All patients are synthetic.

This is an original, public sample of a terminal-style agent task. The agent
receives a small ward chart in mixed units and checks medication orders against
renal dosing rules. The task tests careful data handling (units, order status,
frequency notation, which lab result is current) more than domain knowledge,
because the instruction states the formula, the constants and the rules.

## Layout

```
instruction.md              what the agent is told
task.toml                   task metadata and timeouts
environment/                the agent's only build context
  Dockerfile                python:3.12-slim; copies the chart into /app
  patients.csv  labs.csv  meds.csv  rules.json
solution/
  solve.py                  reference solution (standard library only)
  solve.sh                  oracle entry point
tests/
  test_outputs.py           pytest verifier
  ground_truth.json         frozen expected answer + input hashes
  test.sh                   verifier entry point (writes /logs/verifier/reward.txt)
authoring/
  generate_data.py          seeded generator for environment/ (seed 20261107)
  build_ground_truth.py     runs solve.py and freezes tests/ground_truth.json
  patient_design.json       trap family per patient (authoring only)
  provenance.md             origin of every artefact, hashes, design table
  evidence/
    independent_sqlite.py   second implementation, in SQL
    check_independent.py    ground truth vs solve.py vs SQLite, per patient
    simulate_agents.py      simulated agents graded by the real tests
    run_all.sh              rebuild everything and regenerate the evidence
    results/                committed evidence output
```

## The task

For each of 15 synthetic adults the agent must:

1. Convert weight to kg (`weight_unit` is `kg` or `lb`).
2. Take the **latest** serum creatinine by `collected_at` and convert it to mg/dL
   (`creatinine_unit` is `mg/dL` or `µmol/L`).
3. Compute Cockcroft–Gault creatinine clearance from **actual** body weight.
4. For each **active** order, compute the daily dose from `dose_mg` and the
   frequency string, find the drug's clearance band in `rules.json`, and flag the
   order if the daily dose is greater than that band's maximum.
5. Write one JSON line per patient to `/app/output/dose_check.jsonl` containing
   `crcl_ml_min` (rounded to 0.1) and `flagged_order_ids`.

**Grading.** Every patient must appear exactly once. CrCl must be within 1%
(relative) of the reference, and the set of flagged order ids must match
exactly. All tests must pass for the task to count as solved.

## The traps, and why each matters clinically

Each trap changes exactly one patient's answer, or a small group of patients
that share the same trap family. No patient is exposed to two trap families, so
any failing patient points to one mistake.

| trap | patient | what goes wrong | why it matters on a real ward |
|---|---|---|---|
| µmol/L creatinine treated as mg/dL | PT002 (and the other µmol/L patients) | 150 µmol/L becomes "150 mg/dL", and CrCl falls from 32.5 to 0.4 mL/min | SI and US labs report creatinine in different units, with a factor of 88.4 between them. Mixing them up makes kidney function look catastrophically worse (or better) than it is, so drugs are wrongly withheld or wrongly given at full dose. |
| weight in lb treated as kg | PT005 (and the other lb patients) | 176 lb becomes 176 kg, CrCl rises from 47 to 104, and the over-limit order is missed | Weight-unit mix-ups are a well-known source of dosing errors. In Cockcroft–Gault the error is a factor of 2.2 that inflates clearance, so the patient gets the full-function dose. |
| discontinued order counted as active | PT008 | a stopped 3500 mg order is flagged | The flag goes on an order nobody is taking. False alarms add to alert fatigue, and they can push a clinician to "fix" a dose that does not exist. |
| frequency converted wrongly | PT009 (`q8h`), PT010 (`BD`), PT011 (`TDS`) | `q8h` read as 8/day creates false flags; `BD` read as once daily or `TDS` read as twice daily hides real overdoses | Daily exposure is dose × frequency. "Every 8 hours" means 3 doses a day, not 8. BD and TDS are Latin abbreviations (twice and three times a day) that are easy to misread. |

Two further checks follow directly from the instruction:

- **Latest creatinine** (PT012): an older value from an acute kidney injury
  episode (2.6 mg/dL) appears *after* the recovered value (1.1 mg/dL) in
  `labs.csv`. An agent that keeps whichever row it reads last gets 42 mL/min
  instead of 100 and flags two orders that are fine. Using a stale lab is a
  real cause of over- and under-dosing.
- **Strictly greater** (PT013): an order of exactly 1000 mg/day against a
  1000 mg limit is within the limit and must not be flagged.

### Valid look-alikes

These cases are legitimate. They punish blanket rules that guess units from
the size of the number instead of reading the unit column:

- **PT007, a genuine 150 kg patient recorded in kg.** A rule such as "anything
  over 140 must be pounds" converts the weight to 68 kg, and CrCl falls from
  152 to 69, which falsely flags Cylvarone. Patients of this size are common,
  and they are the patients for whom actual-weight Cockcroft–Gault matters most.
- **PT004, a µmol/L value that looks like a mg/dL number.** A frail,
  sarcopenic 90-year-old weighing 38 kg has a creatinine of 16 µmol/L. Read as
  16 mg/dL it would look like end-stage renal disease. A "values below 20 are
  mg/dL" rule drops CrCl from 124 to 1.4 and flags both orders. Low muscle mass
  means low creatinine, which is exactly why the unit column has to be trusted.

## How the evidence shows the grading is sound

Run `authoring/evidence/run_all.sh`. It needs `python3` and `uv`. The script
regenerates the data from the seed, rebuilds the ground truth, and then runs
two checks. Their output is committed in `authoring/evidence/results/`.

**1. The answer key is right: an independent implementation agrees.**
`independent_sqlite.py` was written against the instruction alone and shares
no code with `solve.py`. It loads the chart into SQLite and computes
everything in SQL: unit conversion in `CASE` expressions, the latest lab via
`MAX(collected_at)`, frequencies through an explicit lookup table, and the
band through a join on NULL-aware bounds. It also asserts that no unit,
frequency or band is unmatched, and that no patient has a tied latest lab.
`check_independent.py` confirms that, for all 15 patients, the ground truth,
`solve.py` and the SQLite version produce identical CrCl at 0.1 mL/min and
identical flagged sets. It also confirms that the ground truth was built from
the committed input files (SHA-256). → `results/independent_agreement.json`

**2. The tests separate right from wrong: simulated agents.**
`simulate_agents.py` runs one configurable agent under many configurations
and grades each output with the real `tests/test_outputs.py` through pytest:

- **Must pass:** the reference `solve.py`; the simulator with no mistakes; and
  defensible variants that a careful agent might choose (factor 88.42, 2.2 or
  2.2046 lb/kg, rounding inputs before the formula, choosing the band from the
  rounded CrCl, unsorted ids). These show the 1% tolerance and set comparison
  are not over-strict.
- **Must fail:** each single trap mistake on its own (µmol/L as mg/dL,
  unit-by-magnitude for creatinine, lb as kg, unit-by-magnitude for weight,
  counting discontinued orders, q8h → 8, BD → 1, TDS → 2, last row wins,
  ≥ instead of >), plus malformed outputs (missing file, empty file, dropped,
  duplicate or extra patient, unrounded CrCl, CrCl as a string).

The same script also checks the data design itself:

- Every mistake changes at least one patient's answer.
- Each mistake changes only patients designed for its trap family, and no
  patient is affected by more than one family. This is the "no two traps on
  one patient" property, measured rather than assumed.
- Every reference CrCl is at least 2% from every band edge of that patient's
  drugs. The smallest margin is 5.8%. Because 2% is more than the 1%
  tolerance, an agent whose CrCl is within tolerance cannot land in a
  different band, so the tolerance can never turn a correct flag set into a
  wrong one.

→ `results/simulation_results.md` (human-readable) and `simulation_results.json`.
The script exits non-zero if any expectation is violated. The committed run
reports no problems.

## Running

```bash
# Reproduce data, ground truth and evidence
authoring/evidence/run_all.sh

# Grade any output file outside the container
OUTPUT_PATH=path/to/dose_check.jsonl uv run --no-project --with pytest==8.3.3 \
  python -m pytest -q tests/test_outputs.py
```

Inside the task container, `solution/solve.sh` writes
`/app/output/dose_check.jsonl` and `tests/test.sh` grades it.

## Disclaimer

This repository is a software benchmark. The patients are synthetic, and the
drugs, clearance bands and dose limits are fictional. It is not medical advice
or clinical dosing guidance, and it must not be used for patient care.
